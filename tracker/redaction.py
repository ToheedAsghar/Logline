"""Terminal-title scrubbing — structured to extend later with more redaction rules."""

from typing import Optional

from tracker.constants import KNOWN_TERMINAL_BUNDLE_IDS


def redact_title(bundle_id: str, title: Optional[str]) -> Optional[str]:
    """Commands run in a terminal can contain secrets, so known terminal apps are
    tracked at the app level only — their window title is never surfaced."""
    if bundle_id in KNOWN_TERMINAL_BUNDLE_IDS:
        return None
    return title
