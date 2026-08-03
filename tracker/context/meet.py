"""Google Meet detection and meeting-name extraction from a window title.

Runs against any captured title regardless of browser, so a browser we've never seen still yields a meeting
name. Unrecognized trailing segments are kept rather than dropped: over-including a suffix is recoverable at
review time, silently losing the meeting name is not.
"""

import re
from typing import Optional, Tuple

SEPARATOR_RE = re.compile(r"\s+[-–—]\s+")

MEET_URL_RE = re.compile(r"^(?:https?://)?meet\.google\.com(?:/\S*)?$", re.IGNORECASE)
MEMORY_RE = re.compile(r"^\d+(?:\.\d+)?\s*[KMGT]?B$", re.IGNORECASE)
PROFILE_RE = re.compile(r"^[^()]+\([^()]*\.[a-z]{2,}\)$", re.IGNORECASE)

NOISE_SEGMENTS = frozenset(
    {
        "google chrome",
        "chrome",
        "mozilla firefox",
        "firefox",
        "microsoft edge",
        "safari",
        "brave",
        "arc",
        "audio playing",
        "camera recording",
        "microphone recording",
        "camera and microphone recording",
        "screen sharing",
        "sharing your screen",
        "high memory usage",
        "meet",
    }
)


def _is_noise(segment: str) -> bool:
    stripped = segment.strip()
    if stripped.lower() in NOISE_SEGMENTS:
        return True
    if MEET_URL_RE.match(stripped):
        return True
    return bool(MEMORY_RE.match(stripped)) or bool(PROFILE_RE.match(stripped))


def parse_meet_title(window_title: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Returns (is_meeting, meeting_name). `meeting_name` is None for an unnamed lobby/landing tab, where the
    title carries no name at all."""
    if not window_title:
        return False, None
    title = window_title.strip()
    if not title:
        return False, None

    if MEET_URL_RE.match(title):
        return True, None

    segments = [segment.strip() for segment in SEPARATOR_RE.split(title) if segment.strip()]
    if not segments or segments[0].lower() != "meet":
        return False, None

    name_parts = [segment for segment in segments[1:] if not _is_noise(segment)]
    if not name_parts:
        return True, None
    return True, " - ".join(name_parts)
