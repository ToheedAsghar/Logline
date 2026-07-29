"""Human-readable console output for the run loop. Formatting only — never touches what gets persisted to
the DB; see storage/db.py for that. Kept to plain string ops (no template engine, no new dependency) since
this runs on every title-change event and the main loop is latency-sensitive.
"""

import sys
from datetime import datetime
from typing import Any, Dict, Optional

_COLOR = sys.stdout.isatty()

_RESET = "\033[0m"
_DIM = "\033[2m"

# (padded label, ANSI color) per event kind. Unknown kinds fall back to their name, uncolored.
_TAGS = {
    "switch": ("SWITCH", "\033[36m"),
    "title": ("TITLE ", "\033[34m"),
    "idle_start": ("IDLE  ", "\033[33m"),
    "idle_end": ("IDLE  ", "\033[33m"),
    "sleep": ("SLEEP ", "\033[35m"),
    "wake": ("WAKE  ", "\033[35m"),
    "lock": ("LOCK  ", "\033[31m"),
    "unlock": ("UNLOCK", "\033[32m"),
}

TITLE_MAX = 60


def _tag(kind: str) -> str:
    label, color = _TAGS.get(kind, (kind.upper(), ""))
    if not _COLOR or not color:
        return f"[{label}]"
    return f"{color}[{label}]{_RESET}"


def truncate(text: str, limit: int = TITLE_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _detail_summary(detail: Optional[Dict[str, Any]]) -> str:
    if not detail:
        return ""
    return " ".join(f"{key}={value}" for key, value in detail.items())


def event(kind: str, headline: str, *, detail: Optional[Dict[str, Any]] = None) -> str:
    """Formats one run-loop event as a single line: `HH:MM:SS [TAG] headline  key=val key2=val2`."""
    ts = datetime.now().strftime("%H:%M:%S")
    timestamp = f"{_DIM}{ts}{_RESET}" if _COLOR else ts
    parts = [timestamp, _tag(kind), headline]
    summary = _detail_summary(detail)
    if summary:
        parts.append(f"{_DIM}{summary}{_RESET}" if _COLOR else summary)
    return "  ".join(parts)
