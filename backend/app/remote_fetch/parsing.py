"""Shared parsing helpers for normalizing timestamps and text payloads from remote sources."""

from datetime import date, datetime, timezone
from typing import Any, Optional


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 string or date into a UTC datetime, returning None on error."""

    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_slack_ts(value: Any) -> Optional[datetime]:
    """Parse a Slack timestamp string (epoch seconds with microsecond fraction) into UTC datetime."""

    if isinstance(value, (int, float)):
        epoch = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            epoch = float(value.strip())
        except ValueError:
            return None
    else:
        return None

    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def split_commit_message(message: Any) -> tuple[Optional[str], Optional[str]]:
    """Split a commit message string into a (subject, body) tuple."""

    if not isinstance(message, str) or not message.strip():
        return None, None

    subject, separator, body = message.strip().partition("\n")
    subject = subject.strip() or None
    if not separator:
        return subject, None

    body = body.strip()
    return subject, body or None


def to_utc_rfc3339(value: datetime) -> str:
    """Format a datetime as an RFC3339 UTC timestamp (trailing 'Z', no microseconds).

    Google Calendar's `timeMin`/`timeMax` query parameters require an explicit time zone offset;
    a naive or offset-less string is rejected outright.
    """

    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def first_non_empty_string(*values: Any) -> Optional[str]:
    """Return the first argument that is a non-blank string, else None."""

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
