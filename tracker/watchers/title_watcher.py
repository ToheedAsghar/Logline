"""Polls the frontmost app's focused window title via the Accessibility API."""

import logging

import ApplicationServices as AS
from AppKit import NSWorkspace
from Foundation import NSTimer

from tracker.constants import TITLE_POLL_INTERVAL_SECONDS
from tracker.context import resolve_context
from tracker.redaction import redact_title

logger = logging.getLogger(__name__)

UNSET = object()


def _is_trusted(prompt: bool) -> bool:
    return bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: prompt}))


def _focused_window_title(pid: int):
    app_element = AS.AXUIElementCreateApplication(pid)
    err, window_ref = AS.AXUIElementCopyAttributeValue(app_element, AS.kAXFocusedWindowAttribute, None)
    if err != AS.kAXErrorSuccess or window_ref is None:
        return None
    err, title = AS.AXUIElementCopyAttributeValue(window_ref, AS.kAXTitleAttribute, None)
    if err != AS.kAXErrorSuccess or title is None:
        return None
    return str(title)


class TitleWatcher:
    """Notifies a callback whenever the frontmost window's (redacted) title differs
    from what was seen on the previous poll.

    callback signature:
        callback(bundle_id: str, app_name: str, window_title: Optional[str], context: ContextResult) -> None

    Without Accessibility permission granted, degrades gracefully: window_title is
    always None, context is empty, and tracking continues at the app level — never
    blocks or raises. Permission is re-checked on every poll, so titles start flowing
    the moment it's granted, without needing a restart.
    """

    def __init__(self, callback):
        self._callback = callback
        self._last_key = UNSET
        self._timer = None

    def start(self):
        if _is_trusted(prompt=True):
            print("title watcher: Accessibility permission granted, tracking window titles.")
        else:
            print(
                "title watcher: Accessibility permission not granted — tracking at app level only "
                "(window_title=NULL). Grant it in System Settings > Privacy & Security > Accessibility."
            )
        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            TITLE_POLL_INTERVAL_SECONDS, True, lambda timer: self._poll()
        )

    def stop(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def reset(self):
        """Forces the next poll to emit even if the title is unchanged.

        Called on app activation. Switching away and back inside one poll interval leaves the title
        identical, so dedup would suppress the event — but the switch already opened a fresh session with
        no context, and only a title_change carries context in.
        """
        self._last_key = UNSET

    def _poll(self):
        frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
        if frontmost is None:
            return
        bundle_id = frontmost.bundleIdentifier() or "unknown"
        app_name = frontmost.localizedName() or "Unknown"

        pid = frontmost.processIdentifier()
        title = None
        trusted = _is_trusted(prompt=False)
        if trusted:
            try:
                title = _focused_window_title(pid)
            except (ValueError, TypeError, RuntimeError, OSError, objc.error):
                title = None
        title = redact_title(bundle_id, title)

        key = (bundle_id, title)
        if key == self._last_key:
            return
        self._last_key = key

        context = resolve_context(
            bundle_id=bundle_id,
            app_name=app_name,
            window_title=title,
            pid=pid if trusted else None,
        )
        try:
            self._callback(bundle_id=bundle_id, app_name=app_name, window_title=title, context=context)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError, objc.error):
            logger.exception("TitleWatcher callback raised; tracker continues running")
