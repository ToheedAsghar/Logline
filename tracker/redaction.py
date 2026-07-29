"""Terminal-title scrubbing — structured to extend later with more redaction rules."""

from typing import Optional

from tracker.constants import KNOWN_TERMINAL_BUNDLE_IDS


def is_redacted(bundle_id: str) -> bool:
    """Whether an app is tracked at the app level only.

    Gates every per-window signal, not just the title: a terminal exposes its working directory via
    AXDocument, so resolving context for one would record the project and branch that redacting the
    title was meant to withhold.
    """
    return bundle_id in KNOWN_TERMINAL_BUNDLE_IDS


def redact_title(bundle_id: str, title: Optional[str]) -> Optional[str]:
    """Commands run in a terminal can contain secrets, so known terminal apps are
    tracked at the app level only — their window title is never surfaced."""
    if is_redacted(bundle_id):
        return None
    return title
