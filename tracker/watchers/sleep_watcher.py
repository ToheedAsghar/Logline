"""Watches for system sleep/wake and screen lock/unlock.

Sleep and lock are kept as distinct events even though both close the open session the same way: a screen lock can
happen without the system ever sleeping (manual lock, screensaver), so collapsing them into one reason would lose a
real distinction. Wake and unlock intentionally do nothing here — the next real event naturally opens the next session.
"""

import logging

import objc
from AppKit import NSWorkspace, NSWorkspaceDidWakeNotification, NSWorkspaceWillSleepNotification
from Foundation import NSDistributedNotificationCenter, NSObject

from tracker.constants import SCREEN_LOCKED_NOTIFICATION, SCREEN_UNLOCKED_NOTIFICATION, WATCHER_ERROR_MSG

logger = logging.getLogger(__name__)


class _PowerObserver(NSObject):
    def initWithCallbacks_(self, callbacks):
        self = objc.super(_PowerObserver, self).init()
        if self is None:
            return None
        self._on_sleep, self._on_wake, self._on_lock, self._on_unlock = callbacks
        return self

    def willSleep_(self, notification):
        try:
            self._on_sleep()
        except Exception:
            logger.exception(WATCHER_ERROR_MSG, "SleepWatcher on_sleep callback")

    def didWake_(self, notification):
        try:
            self._on_wake()
        except Exception:
            logger.exception(WATCHER_ERROR_MSG, "SleepWatcher on_wake callback")

    def screenLocked_(self, notification):
        try:
            self._on_lock()
        except Exception:
            logger.exception(WATCHER_ERROR_MSG, "SleepWatcher on_lock callback")

    def screenUnlocked_(self, notification):
        try:
            self._on_unlock()
        except Exception:
            logger.exception(WATCHER_ERROR_MSG, "SleepWatcher on_unlock callback")


class SleepWatcher:
    """Notifies callbacks on system sleep/wake and screen lock/unlock.

    callback signatures: on_sleep() -> None, on_wake() -> None,
                          on_lock() -> None, on_unlock() -> None
    """

    def __init__(self, on_sleep, on_wake, on_lock, on_unlock):
        self._observer = _PowerObserver.alloc().initWithCallbacks_((on_sleep, on_wake, on_lock, on_unlock))
        self._workspace_center = NSWorkspace.sharedWorkspace().notificationCenter()
        self._distributed_center = NSDistributedNotificationCenter.defaultCenter()

    def start(self):
        self._workspace_center.addObserver_selector_name_object_(
            self._observer, "willSleep:", NSWorkspaceWillSleepNotification, None
        )
        self._workspace_center.addObserver_selector_name_object_(
            self._observer, "didWake:", NSWorkspaceDidWakeNotification, None
        )
        self._distributed_center.addObserver_selector_name_object_(
            self._observer, "screenLocked:", SCREEN_LOCKED_NOTIFICATION, None
        )
        self._distributed_center.addObserver_selector_name_object_(
            self._observer, "screenUnlocked:", SCREEN_UNLOCKED_NOTIFICATION, None
        )

    def stop(self):
        self._workspace_center.removeObserver_(self._observer)
        self._distributed_center.removeObserver_(self._observer)
