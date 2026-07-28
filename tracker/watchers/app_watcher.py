"""Watches for frontmost-application switches via NSWorkspace notifications."""

import logging

import objc
from AppKit import NSWorkspace, NSWorkspaceApplicationKey, NSWorkspaceDidActivateApplicationNotification
from Foundation import NSObject

logger = logging.getLogger(__name__)


class _ActivationObserver(NSObject):
    def initWithCallback_(self, callback):
        self = objc.super(_ActivationObserver, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def appActivated_(self, notification):
        try:
            user_info = notification.userInfo()
            app = user_info.get(NSWorkspaceApplicationKey) if user_info else None
            if app is None:
                return
            bundle_id = app.bundleIdentifier() or "unknown"
            app_name = app.localizedName() or "Unknown"
            self._callback(bundle_id=bundle_id, app_name=app_name)
        except Exception:
            logger.exception("AppWatcher callback raised; tracker continues running")


class AppWatcher:
    """Notifies a callback every time the frontmost application changes.

    callback signature: callback(bundle_id: str, app_name: str) -> None
    """

    def __init__(self, callback):
        self._callback = callback
        self._observer = _ActivationObserver.alloc().initWithCallback_(callback)
        self._center = NSWorkspace.sharedWorkspace().notificationCenter()

    def start(self):
        self._center.addObserver_selector_name_object_(
            self._observer,
            "appActivated:",
            NSWorkspaceDidActivateApplicationNotification,
            None,
        )

    def stop(self):
        self._center.removeObserver_(self._observer)
