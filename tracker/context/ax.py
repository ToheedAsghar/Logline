"""The one Accessibility read the context layer needs: the focused window's AXDocument.

Kept apart from the resolvers so they stay pure and testable. Mirrors TitleWatcher's posture — any AX failure
yields None and tracking continues, never an exception.
"""

import logging
from typing import Optional

import ApplicationServices as AS

logger = logging.getLogger(__name__)


def focused_document_url(pid: int) -> Optional[str]:
    """Returns the frontmost window's AXDocument (a file:// URL for editors/terminals, an http(s) URL for
    Chrome), or None. An advertised AXDocument attribute can still read back empty or kAXErrorNoValue, so the
    value is what's checked — never the attribute list."""
    try:
        app_element = AS.AXUIElementCreateApplication(pid)
        err, window_ref = AS.AXUIElementCopyAttributeValue(app_element, AS.kAXFocusedWindowAttribute, None)
        if err != AS.kAXErrorSuccess or window_ref is None:
            return None
        err, document = AS.AXUIElementCopyAttributeValue(window_ref, "AXDocument", None)
        if err != AS.kAXErrorSuccess or not document:
            return None
        return str(document)
    except (ValueError, TypeError, RuntimeError, OSError, objc.error):
        logger.debug("AXDocument read failed for pid %s; continuing without it", pid, exc_info=True)
        return None
