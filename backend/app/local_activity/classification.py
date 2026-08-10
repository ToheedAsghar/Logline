"""Classify raw tracker sessions into deterministic coarse activity categories."""

import enum
import json
import re
from dataclasses import dataclass
from typing import Optional

from app.local_activity.constants import (
    IDLE_BUNDLE_IDS, KNOWN_COMMS_BUNDLE_IDS, KNOWN_IDE_BUNDLE_IDS, KNOWN_TERMINAL_BUNDLE_IDS,
)


class SessionCategory(str, enum.Enum):
    """Define the coarse categories used before aggregation."""

    idle = "Idle"
    meeting = "Meeting"
    code_review = "Code Review"
    coding = "Coding"
    documentation = "Documentation"
    comms = "Comms"
    admin = "Admin"


@dataclass(frozen=True)
class SessionClassification:
    """Contain a session category and an optional meeting name."""

    category: SessionCategory
    meeting_name: Optional[str] = None


MEET_URL_RE = re.compile(r"meet\.google\.com", re.IGNORECASE)
ZOOM_URL_RE = re.compile(r"zoom\.us", re.IGNORECASE)
TEAMS_URL_RE = re.compile(r"teams\.microsoft\.com", re.IGNORECASE)
MEET_TITLE_PREFIX_RE = re.compile(r"^\s*meet\b", re.IGNORECASE)
MEET_TITLE_SEPARATOR_RE = re.compile(r"\s+[-–—]\s+")
MEET_MEMORY_RE = re.compile(r"^\d+(?:\.\d+)?\s*[KMGT]?B$", re.IGNORECASE)
MEET_PROFILE_RE = re.compile(r"^[^()]+\([^()]*\.[a-z]{2,}\)$", re.IGNORECASE)
MEET_TITLE_NOISE = frozenset(
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

CODE_REVIEW_URL_RE = re.compile(
    r"github\.com/[^/\s]+/[^/\s]+/pull/|gitlab\.com/.+/-/merge_requests/|bitbucket\.org/[^/\s]+/[^/\s]+/pull-requests/",
    re.IGNORECASE,
)
CODE_REVIEW_TITLE_RE = re.compile(r"pull request|merge request", re.IGNORECASE)

DOCUMENTATION_URL_RE = re.compile(r"docs\.google\.com|notion\.so|\.atlassian\.net/wiki", re.IGNORECASE)
DOCUMENTATION_TITLE_RE = re.compile(r"google docs|notion|confluence", re.IGNORECASE)

COMMS_URL_RE = re.compile(
    r"slack\.com|discord\.com|web\.whatsapp\.com|mail\.google\.com|outlook\.office\.com",
    re.IGNORECASE,
)
COMMS_TITLE_RE = re.compile(r"\bslack\b|\bwhatsapp\b|\bdiscord\b|\bgmail\b|\boutlook\b", re.IGNORECASE)

AI_ASSISTANT_URL_RE = re.compile(r"claude\.ai", re.IGNORECASE)
AI_ASSISTANT_TITLE_RE = re.compile(r"(?:^|[-–—])\s*claude\s*$", re.IGNORECASE)

def parse_context_detail(raw: Optional[str]) -> dict:
    """Parse tracker context JSON, returning an empty dict for malformed or non-object input."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_meeting(detail: dict, window_title: Optional[str]) -> bool:
    """Return whether a session is a meeting.

    Trust `is_meeting` when present. Otherwise recognize supported meeting URLs and legacy titles beginning with
    `Meet`; the word-boundary rule prevents matching `Meeting`.
    """
    if "is_meeting" in detail:
        return detail.get("is_meeting") is True
    text = window_title or ""
    url = detail.get("url") or ""
    haystack = f"{text} {url}"
    return bool(
        MEET_URL_RE.search(haystack)
        or ZOOM_URL_RE.search(haystack)
        or TEAMS_URL_RE.search(haystack)
        or MEET_TITLE_PREFIX_RE.match(text.strip())
    )


def _meeting_name(detail: dict, window_title: Optional[str]) -> Optional[str]:
    """Return an explicit meeting name or parse one from a legacy Meet title."""
    explicit_name = detail.get("meeting_name")
    if explicit_name:
        return explicit_name
    if not window_title:
        return None

    segments = [segment.strip() for segment in MEET_TITLE_SEPARATOR_RE.split(window_title.strip()) if segment.strip()]
    if not segments or segments[0].lower() != "meet":
        return None
    name_parts = [
        segment
        for segment in segments[1:]
        if segment.lower() not in MEET_TITLE_NOISE
        and not MEET_MEMORY_RE.match(segment)
        and not MEET_PROFILE_RE.match(segment)
        and not MEET_URL_RE.fullmatch(segment)
    ]
    return " - ".join(name_parts) or None


def _is_code_review(detail: dict, window_title: Optional[str]) -> bool:
    """Return whether URL or title evidence identifies code review activity."""
    url = detail.get("url") or ""
    text = window_title or ""
    return bool(CODE_REVIEW_URL_RE.search(url) or CODE_REVIEW_TITLE_RE.search(text))


def _is_documentation(detail: dict, window_title: Optional[str]) -> bool:
    """Return whether URL or title evidence identifies documentation activity."""
    url = detail.get("url") or ""
    text = window_title or ""
    return bool(DOCUMENTATION_URL_RE.search(url) or DOCUMENTATION_TITLE_RE.search(text))


def _is_comms(detail: dict, window_title: Optional[str], bundle_id: Optional[str]) -> bool:
    """Return whether bundle, URL, or title evidence identifies communications activity."""
    if bundle_id in KNOWN_COMMS_BUNDLE_IDS:
        return True
    url = detail.get("url") or ""
    text = window_title or ""
    return bool(COMMS_URL_RE.search(url) or COMMS_TITLE_RE.search(text))


def _is_idle(bundle_id: Optional[str]) -> bool:
    """Return whether a bundle id represents locked-screen idle activity."""
    return bundle_id in IDLE_BUNDLE_IDS


def _is_ai_assistant_chat(detail: dict, window_title: Optional[str]) -> bool:
    """Return whether URL or title evidence identifies a claude.ai browser chat session.

    Browser tab titles for claude.ai read "Claude" for an unnamed chat, or "<chat name> - Claude" once named --
    never the bare word "Claude" elsewhere in a longer title, hence the anchored suffix match rather than a
    plain substring/word-boundary check.
    """
    url = detail.get("url") or ""
    text = (window_title or "").strip()
    return bool(AI_ASSISTANT_URL_RE.search(url) or AI_ASSISTANT_TITLE_RE.search(text))


def _is_coding(bundle_id: Optional[str], detail: dict, window_title: Optional[str]) -> bool:
    """Return whether a bundle id identifies an IDE or terminal, or evidence identifies an AI-assistant chat.

    An AI-assistant browser session is grouped with Coding rather than Comms: it is development-support work, not
    person-to-person messaging -- confirmed against hand-filled ground truth (see references/pipeline.py's
    activity_of()), and previously fell through to the Admin catch-all with no matching predicate at all.
    """
    return (
        bundle_id in KNOWN_IDE_BUNDLE_IDS
        or bundle_id in KNOWN_TERMINAL_BUNDLE_IDS
        or _is_ai_assistant_chat(detail, window_title)
    )


def classify_session(
    *,
    bundle_id: Optional[str],
    window_title: Optional[str],
    project_path: Optional[str],
    context_detail: Optional[str],
) -> SessionClassification:
    """Classify one raw session by priority: Idle, Meeting, Code Review, Documentation, Comms, Coding, then Admin."""
    if _is_idle(bundle_id):
        return SessionClassification(category=SessionCategory.idle)

    detail = parse_context_detail(context_detail)

    if _is_meeting(detail, window_title):
        return SessionClassification(category=SessionCategory.meeting, meeting_name=_meeting_name(detail, window_title))
    if _is_code_review(detail, window_title):
        return SessionClassification(category=SessionCategory.code_review)
    if _is_documentation(detail, window_title):
        return SessionClassification(category=SessionCategory.documentation)
    if _is_comms(detail, window_title, bundle_id):
        return SessionClassification(category=SessionCategory.comms)
    if _is_coding(bundle_id, detail, window_title):
        return SessionClassification(category=SessionCategory.coding)
    return SessionClassification(category=SessionCategory.admin)
