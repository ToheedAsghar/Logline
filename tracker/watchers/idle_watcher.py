"""Detects sustained keyboard/mouse inactivity via CGEventSource. Backdates the idle transition to when input actually
stopped, not when this watcher's poll noticed."""

import logging
from datetime import datetime, timedelta

from Foundation import NSTimer
from Quartz import CGEventSourceSecondsSinceLastEventType, kCGAnyInputEventType, kCGEventSourceStateCombinedSessionState

from tracker.constants import IDLE_CHECK_INTERVAL_SECONDS, IDLE_THRESHOLD_SECONDS, WATCHER_ERROR_MSG

logger = logging.getLogger(__name__)


def _seconds_since_last_input() -> float:
    return CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType)


class IdleWatcher:
    """callback signatures:
        on_idle_start(stopped_at: datetime) -> None   # backdated to when input actually stopped
        on_idle_end() -> None                          # fired the moment input resumes
    """

    def __init__(self, on_idle_start, on_idle_end, idle_threshold_seconds: float = IDLE_THRESHOLD_SECONDS):
        self._on_idle_start = on_idle_start
        self._on_idle_end = on_idle_end
        self._idle_threshold_seconds = idle_threshold_seconds
        self._is_idle = False
        self._timer = None

    def start(self):
        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            IDLE_CHECK_INTERVAL_SECONDS, True, lambda timer: self._poll()
        )

    def stop(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def mark_active(self):
        """Called by another watcher that has independently confirmed the user is active (e.g. a real app switch).
        Silently resets idle state without firing on_idle_end — the switch itself already accounts for the transition,
        so the next poll must not also fire a spurious idle_end for input that already resumed."""

        self._is_idle = False

    def resync(self):
        """Checks whether the user is actually idle right now, using the real system clock for last keyboard/mouse
        input — not any assumption about what just happened.

        Updates the internal idle/active flag to match that real answer. Does NOT trigger on_idle_start or on_idle_end
        — it only fixes the flag itself, quietly, so it's correct the next time something checks it."""

        self._is_idle = _seconds_since_last_input() >= self._idle_threshold_seconds

    def _poll(self):
        idle_for = _seconds_since_last_input()
        if not self._is_idle and idle_for >= self._idle_threshold_seconds:
            self._is_idle = True
            stopped_at = datetime.now().astimezone() - timedelta(seconds=idle_for)
            try:
                self._on_idle_start(stopped_at)
            except Exception:
                logger.exception(WATCHER_ERROR_MSG, "IdleWatcher on_idle_start callback")
        elif self._is_idle and idle_for < self._idle_threshold_seconds:
            self._is_idle = False
            try:
                self._on_idle_end()
            except Exception:
                logger.exception(WATCHER_ERROR_MSG, "IdleWatcher on_idle_end callback")
