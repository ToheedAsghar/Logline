"""Pass 1 classification: a coarse, deterministic category per raw tracker session.

This is the first of two distinct classification passes in the pipeline. Pass 1 (this module) runs here,
before aggregation, so that aggregation can group sessions by what kind of activity they represent and stop
fusing a meeting into whatever coding happened to sit next to it in time. Pass 2 -- a finer-grained category
(e.g. Coding vs. Debugging vs. Testing) assigned to already-formed, category-pure blocks later in the
pipeline -- is a separate, not-yet-built stage; today that finer grain is still the LLM's own `EntryTag`
choice at Stage 5, unchanged by this module. Do not conflate the two.

Every rule here is a deterministic string/URL match, never a guess: a session that matches nothing falls
through to `SessionCategory.admin` rather than being left unclassified or dropped. `admin` is a real,
counted category -- the point of this pass is that nothing is ever silently excluded from the day, which is
exactly the bug it replaces (the old pipeline dropped every session with no `project_path`, which was most
browser activity).
"""

import enum
import json
import re
from dataclasses import dataclass
from typing import Optional

from app.local_activity.constants import (
    IDLE_BUNDLE_IDS, KNOWN_COMMS_BUNDLE_IDS, KNOWN_IDE_BUNDLE_IDS, KNOWN_TERMINAL_BUNDLE_IDS,
)


class SessionCategory(str, enum.Enum):
    """Coarse activity category assigned per raw session, before aggregation.

    Seven values only -- this is Pass 1's whole vocabulary. Enum string values are rendered directly into
    the evidence bundle, so they are human-readable on purpose. `idle` is proven non-work (screen locked),
    never sent to the reconciliation model -- see `_gather_evidence` in `app/agent/reconciliation/routers.py`.
    """

    idle = "Idle"
    meeting = "Meeting"
    code_review = "Code Review"
    coding = "Coding"
    documentation = "Documentation"
    comms = "Comms"
    admin = "Admin"


@dataclass(frozen=True)
class SessionClassification:
    """The result of classifying one session: its category, plus the meeting name if one was found.

    `meeting_name` is only ever populated when `category` is `meeting`, and is None for an unnamed
    lobby/landing tab -- see `tracker/context/meet.py::parse_meet_title`, whose output this reads.
    """

    category: SessionCategory
    meeting_name: Optional[str] = None


MEET_URL_RE = re.compile(r"meet\.google\.com", re.IGNORECASE)
ZOOM_URL_RE = re.compile(r"zoom\.us", re.IGNORECASE)
TEAMS_URL_RE = re.compile(r"teams\.microsoft\.com", re.IGNORECASE)
MEET_TITLE_PREFIX_RE = re.compile(r"^\s*meet\b", re.IGNORECASE)

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


def _parse_context_detail(raw: Optional[str]) -> dict:
    """Best-effort parse of the tracker's `context_detail` JSON string.

    Malformed or absent JSON resolves to an empty dict rather than raising -- classification must never
    crash a reconciliation run over one bad row; it just falls through to a later, less-specific rule.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_meeting(detail: dict, window_title: Optional[str]) -> bool:
    """The tracker already detects Google Meet client-side (`tracker/context/meet.py`) and records it in
    `context_detail`; that is the primary signal, and an explicit `is_meeting: false` is trusted as-is --
    it is not overridden by the fallback below. The title/URL regex fallback only runs when the key is
    absent entirely, for rows synced before `context_detail` carried `is_meeting`, or for meeting tools the
    tracker doesn't parse. `MEET_TITLE_PREFIX_RE` covers a Meet tab's processed title ("Meet - <name>" or
    bare "Meet", per `parse_meet_title`), which contains no "meet.google.com" text at all; it requires
    "Meet" as its own leading word so it never matches "Meeting"."""
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


def _is_code_review(detail: dict, window_title: Optional[str]) -> bool:
    """Checks both a URL-shaped pattern (against `context_detail.url`, populated by Chrome but never by
    Firefox -- see `resolve_firefox` in tracker/context/resolvers.py) and a title-shaped pattern (against
    the raw window title, always available, and a browser tab's actual page `<title>` text rather than its
    URL -- a real GitHub PR tab's title reads "... Pull Request #58 ... GitHub", never the URL). Without the
    title-shaped check, a Firefox user could never be classified Code Review at all."""
    url = detail.get("url") or ""
    text = window_title or ""
    return bool(CODE_REVIEW_URL_RE.search(url) or CODE_REVIEW_TITLE_RE.search(text))


def _is_documentation(detail: dict, window_title: Optional[str]) -> bool:
    """Same URL-shaped-plus-title-shaped approach as `_is_code_review`."""
    url = detail.get("url") or ""
    text = window_title or ""
    return bool(DOCUMENTATION_URL_RE.search(url) or DOCUMENTATION_TITLE_RE.search(text))


def _is_comms(detail: dict, window_title: Optional[str], bundle_id: str) -> bool:
    """Same URL-shaped-plus-title-shaped approach as `_is_code_review`, plus a bundle id check for native
    (non-browser) comms apps, which have no URL or brand text in their window title at all."""
    if bundle_id in KNOWN_COMMS_BUNDLE_IDS:
        return True
    url = detail.get("url") or ""
    text = window_title or ""
    return bool(COMMS_URL_RE.search(url) or COMMS_TITLE_RE.search(text))


def _is_idle(bundle_id: str) -> bool:
    """The tracker's IdleWatcher (keyboard/mouse input) does not fire while the screen is locked, so a
    locked session survives the `is_idle=false` filter upstream and needs this bundle-id check instead."""
    return bundle_id in IDLE_BUNDLE_IDS


def _is_coding(bundle_id: str) -> bool:
    """An IDE or terminal bundle is coding activity whether or not `project_path` resolved. Real IDE/terminal
    sessions frequently arrive with no project_path (a tracker-side gap, not evidence the work wasn't real),
    so requiring it here would misclassify genuine coding time into the `admin` catch-all instead. `project`
    stays None on the resulting block either way -- this only fixes the category, not project attribution."""
    return bundle_id in KNOWN_IDE_BUNDLE_IDS or bundle_id in KNOWN_TERMINAL_BUNDLE_IDS


def classify_session(
    *,
    bundle_id: str,
    window_title: Optional[str],
    project_path: Optional[str],
    context_detail: Optional[str],
) -> SessionClassification:
    """Classify one raw tracker session into a `SessionCategory`, deterministically.

    Rules are checked in a fixed priority order and the first match wins -- Idle, then Meeting, then Code
    Review, then Documentation, then Comms, then Coding, then Admin as the catch-all. Idle is checked first
    because a locked screen means nothing else in `detail`/`window_title` reflects real activity, whatever
    it happens to contain. The remaining order matters when a title could plausibly match more than one rule
    (e.g. a Slack thread with a GitHub link in its title): the more specific, higher-signal categories are
    checked first.

    Never raises and never returns anything other than a `SessionClassification` -- an unrecognized session
    is `SessionCategory.admin`, not an error and not a reason to drop the row.
    """
    if _is_idle(bundle_id):
        return SessionClassification(category=SessionCategory.idle)

    detail = _parse_context_detail(context_detail)

    if _is_meeting(detail, window_title):
        return SessionClassification(category=SessionCategory.meeting, meeting_name=detail.get("meeting_name"))
    if _is_code_review(detail, window_title):
        return SessionClassification(category=SessionCategory.code_review)
    if _is_documentation(detail, window_title):
        return SessionClassification(category=SessionCategory.documentation)
    if _is_comms(detail, window_title, bundle_id):
        return SessionClassification(category=SessionCategory.comms)
    if _is_coding(bundle_id):
        return SessionClassification(category=SessionCategory.coding)
    return SessionClassification(category=SessionCategory.admin)
