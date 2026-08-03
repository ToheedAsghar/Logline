"""Polls the frontmost app's focused window title via the Accessibility API."""

import logging

import ApplicationServices as AS
from AppKit import NSWorkspace
from Foundation import NSTimer

from tracker.constants import (
    AX_GRANTED_MSG, AX_NOT_GRANTED_MSG, TITLE_POLL_INTERVAL_SECONDS, UNKNOWN_APP_NAME, UNKNOWN_BUNDLE_ID,
    WATCHER_ERROR_MSG,
)
from tracker.context import UNSET as READ_DOCUMENT_URL
from tracker.context import resolve_context
from tracker.context.models import ContextResult
from tracker.redaction import is_redacted, redact_title

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
    """Call a callback when the frontmost window's redacted title changes.

    callback signature:
        callback(bundle_id: str, app_name: str, window_title: Optional[str], context: ContextResult) -> None

    Without Accessibility permission, window_title is always None and title-based context is empty. Tracking
    continues at the app level. Permission is checked on every poll, so titles start flowing after access is granted
    without a restart.

    Always pass the PID. Terminal tool detection reads process data, not Accessibility, so it works without access.
    Withhold `document_url` when access is not trusted.
    """

    def __init__(self, callback):
        self._callback = callback
        self._last_key = UNSET
        self._timer = None

    def start(self):
        if _is_trusted(prompt=True):
            print(AX_GRANTED_MSG)
        else:
            print(AX_NOT_GRANTED_MSG)
        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            TITLE_POLL_INTERVAL_SECONDS, True, lambda timer: self._poll()
        )

    def stop(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def reset(self):
        """Make the next poll emit even when the title has not changed.

        App activation calls this. Switching away and back within one poll interval can leave the title unchanged.
        Without the reset, duplicate filtering would hide the event. The switch already opened a fresh session, and
        only a title change adds its context.
        """
        self._last_key = UNSET

    def _poll(self):
        frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
        if frontmost is None:
            return
        bundle_id = frontmost.bundleIdentifier() or UNKNOWN_BUNDLE_ID
        app_name = frontmost.localizedName() or UNKNOWN_APP_NAME

        pid = frontmost.processIdentifier()
        title = None
        trusted = _is_trusted(prompt=False)
        if trusted:
            try:
                title = _focused_window_title(pid)
            except Exception:
                title = None
        title = redact_title(bundle_id, title)

        context = None
        if is_redacted(bundle_id):
            context = self._resolve_context_safely(
                bundle_id, app_name, title, pid, READ_DOCUMENT_URL if trusted else None
            )
            key = (bundle_id, title, context.project_path, tuple(sorted(context.detail.items())))
        else:
            key = (bundle_id, title)
        if key == self._last_key:
            return
        self._last_key = key

        if context is None:
            context = self._resolve_context_safely(
                bundle_id, app_name, title, pid, READ_DOCUMENT_URL if trusted else None
            )
        try:
            self._callback(bundle_id=bundle_id, app_name=app_name, window_title=title, context=context)
        except Exception:
            logger.exception(WATCHER_ERROR_MSG, "TitleWatcher callback")

    @staticmethod
    def _resolve_context_safely(bundle_id, app_name, title, pid, document_url):
        """Resolve context without letting an unexpected resolver error stop polling."""
        try:
            return resolve_context(
                bundle_id=bundle_id,
                app_name=app_name,
                window_title=title,
                pid=pid,
                document_url=document_url,
            )
        except Exception:
            logger.exception(WATCHER_ERROR_MSG, "TitleWatcher context resolver")
            return ContextResult()
