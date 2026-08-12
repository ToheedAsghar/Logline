"""Two-layer redaction for logs: a field-name denylist, and a scan for secret-shaped text.

Both run as structlog processors on every log call, so no call site can forget to sanitize. A third function
here emits a WARNING when either layer redacts something, so a redaction is visible instead of silent.
"""

import re
from typing import Any

import structlog

REDACTED_MARKER = "<redacted>"

_SIGNAL_GUARD_KEY = "_is_redaction_signal"

FORBIDDEN_LOG_FIELDS = frozenset({
    "evidence_text",
    "evidence",
    "evidence_bundle",
    "evidence_blob",
    "raw_evidence",
    "window_title",
    "window_titles",
    "title_digest",
    "titles",
    "prompt",
    "prompt_messages",
    "messages",
    "response",
    "response_body",
    "content",
    "completion",
    "token",
    "tokens",
    "authorization",
    "bearer",
    "bearer_token",
    "raw_token",
    "secret_token",
    "id_token",
    "access_token",
    "refresh_token",
})

LEAK_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("jwt_shaped_token", re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("oauth_query_param", re.compile(r"[?&](?:state|code|token|access_token|refresh_token)=[^&\s]+", re.I)),
    ("local_home_path", re.compile(r"/Users/[^/\s]+(?:/[^\s]*)?")),
    ("stripe_style_key", re.compile(r"\b(?:sk|pk|rk|live)_[A-Za-z0-9]{16,}\b")),
)


def _source_logger_name(event_dict: dict) -> str | None:
    """Returns the name of the logger that made this log call, or None if it isn't known."""
    record = event_dict.get("_record")
    return record.name if record is not None else None


def _emit_redaction_signal(layer: str, matched: list[str], event_dict: dict) -> None:
    """Logs a WARNING saying which layer redacted something and where it happened.

    Only logs names (which field or pattern matched, which logger it came from), never the actual
    secret value, so this warning can't itself leak what it's reporting on.
    """
    structlog.get_logger("app.core.redaction").warning(
        "redaction_triggered",
        layer=layer,
        matched=sorted(set(matched)),
        source_logger=_source_logger_name(event_dict),
        source_level=event_dict.get("level"),
        _is_redaction_signal=True,
    )


def _redact_nested(value: Any, matched: list[str]) -> Any:
    """Walks into a dict, list, tuple, or set so a forbidden key nested inside it still gets redacted."""
    if isinstance(value, dict):
        result = {}
        for key, nested in value.items():
            if key.lower() in FORBIDDEN_LOG_FIELDS:
                result[key] = REDACTED_MARKER
                matched.append(key)
            else:
                result[key] = _redact_nested(nested, matched)
        return result
    if isinstance(value, list):
        return [_redact_nested(item, matched) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_nested(item, matched) for item in value)
    if isinstance(value, set):
        return {_redact_nested(item, matched) for item in value}
    return value


def redact_forbidden_fields(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Layer 2: if a log field's name is in FORBIDDEN_LOG_FIELDS, replace its whole value with "<redacted>".

    Checks field names, not their content, so it also works on nested fields, e.g.
    `{"entry": {"evidence_text": ...}}`. Matching ignores case.
    """
    if event_dict.get(_SIGNAL_GUARD_KEY):
        return event_dict

    matched: list[str] = []
    for key in list(event_dict):
        if key.lower() in FORBIDDEN_LOG_FIELDS:
            event_dict[key] = REDACTED_MARKER
            matched.append(key)
        else:
            event_dict[key] = _redact_nested(event_dict[key], matched)

    if matched:
        _emit_redaction_signal("field_denylist", matched, event_dict)
    return event_dict


def _scan_value(value: Any, matched: list[str]) -> Any:
    """Walks into a value and blanks out any part of a string that matches LEAK_PATTERNS.

    Handles plain strings, dicts, lists, tuples, and sets. Anything else (e.g. a custom object) is left as
    is, since it isn't turned into a string until after this runs and can't be scanned yet.
    """
    if isinstance(value, str):
        redacted = value
        for name, pattern in LEAK_PATTERNS:
            if pattern.search(redacted):
                matched.append(name)
            redacted = pattern.sub(REDACTED_MARKER, redacted)
        return redacted
    if isinstance(value, dict):
        return {key: _scan_value(nested, matched) for key, nested in value.items()}
    if isinstance(value, list):
        return [_scan_value(item, matched) for item in value]
    if isinstance(value, tuple):
        return tuple(_scan_value(item, matched) for item in value)
    if isinstance(value, set):
        return {_scan_value(item, matched) for item in value}
    return value


def scan_for_leak_patterns(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Layer 3: scans every string value in a log for secret-shaped text and blanks out just that part.

    Only redacts the matching part of a string, not the whole message, so normal log text like "could not
    connect to 'github' MCP server" stays readable even when a secret is found nearby. This only catches the
    four secret shapes in LEAK_PATTERNS (JWT-shaped tokens, OAuth query params, local home paths, Stripe-style
    keys) -- a new secret shape needs a new pattern added here.

    Known gaps, not fixed here: a secret split across two separate log calls won't be caught, since each log
    call is checked on its own; and an object that only reveals a secret through its own `__str__` isn't
    scanned, since it's turned into a string after this function runs.
    """
    if event_dict.get(_SIGNAL_GUARD_KEY):
        return event_dict

    matched: list[str] = []
    for key in list(event_dict):
        event_dict[key] = _scan_value(event_dict[key], matched)

    if matched:
        _emit_redaction_signal("content_scan", matched, event_dict)
    return event_dict
