"""Regression tests for IdleWatcher's mark_active()/resync() split.

Both methods correct IdleWatcher's internal _is_idle flag without firing a
callback. The distinction: mark_active() assumes the caller's event proves
real activity (an app switch); resync() makes no such assumption (a title
change can happen with no real input) and instead re-reads ground truth from
CGEventSource.
"""

import tracker.watchers.idle_watcher as idle_watcher_module
from tracker.watchers.idle_watcher import IdleWatcher

THRESHOLD = 240


class _Recorder:
    def __init__(self):
        self.idle_start_calls = []
        self.idle_end_calls = 0

    def on_idle_start(self, stopped_at):
        self.idle_start_calls.append(stopped_at)

    def on_idle_end(self):
        self.idle_end_calls += 1


def _make_watcher():
    recorder = _Recorder()
    watcher = IdleWatcher(
        on_idle_start=recorder.on_idle_start,
        on_idle_end=recorder.on_idle_end,
        idle_threshold_seconds=THRESHOLD,
    )
    return watcher, recorder


class TestMarkActiveSuppressesSpuriousIdleEnd:
    """Switch/idle desync bug: without mark_active() resetting the watcher's
    stale is_idle=True flag on a real app switch, the next poll (which sees a
    just-interacted-with, non-idle CGEventSource reading) fires an on_idle_end
    that the manager didn't ask for, closing the switch's freshly-opened
    active session and reopening a spurious duplicate."""

    def test_mark_active_resets_flag_without_firing_callback(self):
        watcher, recorder = _make_watcher()
        watcher._is_idle = True

        watcher.mark_active()

        assert watcher._is_idle is False
        assert recorder.idle_end_calls == 0
        assert recorder.idle_start_calls == []

    def test_poll_after_mark_active_does_not_fire_idle_end(self, monkeypatch):
        watcher, recorder = _make_watcher()
        watcher._is_idle = True
        watcher.mark_active()

        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: 0.5)
        watcher._poll()

        assert recorder.idle_end_calls == 0

    def test_without_mark_active_stale_flag_fires_spurious_idle_end(self, monkeypatch):
        """Same setup, but skip mark_active() — proves the bug it fixes is real."""
        watcher, recorder = _make_watcher()
        watcher._is_idle = True  # stale: switch happened but nothing told the watcher

        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: 0.5)
        watcher._poll()

        assert recorder.idle_end_calls == 1


class TestResyncCorrectsFlagWithoutAssumingActivity:
    """A title change can fire with no real input. resync() must re-read ground
    truth from CGEventSource so a later poll doesn't act on a stale flag —
    but, unlike mark_active(), must never claim the user is active."""

    def test_resync_marks_idle_when_ground_truth_is_idle(self, monkeypatch):
        watcher, recorder = _make_watcher()
        assert watcher._is_idle is False

        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: THRESHOLD + 10)
        watcher.resync()

        assert watcher._is_idle is True
        assert recorder.idle_start_calls == []
        assert recorder.idle_end_calls == 0

    def test_resync_marks_active_when_ground_truth_is_active(self, monkeypatch):
        watcher, recorder = _make_watcher()
        watcher._is_idle = True

        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: 1.0)
        watcher.resync()

        assert watcher._is_idle is False
        assert recorder.idle_start_calls == []
        assert recorder.idle_end_calls == 0

    def test_poll_after_resync_does_not_double_fire_idle_start(self, monkeypatch):
        watcher, recorder = _make_watcher()
        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: THRESHOLD + 10)

        watcher.resync()
        assert recorder.idle_start_calls == []

        watcher._poll()
        assert recorder.idle_start_calls == []

    def test_without_resync_stale_flag_lets_next_poll_fire_idle_start_late(self, monkeypatch):
        """Same ground truth, but skip resync() — proves the bug it fixes is real:
        the poll fires on_idle_start anyway, only later and with a shorter
        backdated idle span than what actually elapsed."""
        watcher, recorder = _make_watcher()
        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: THRESHOLD + 10)

        watcher._poll()

        assert len(recorder.idle_start_calls) == 1


class TestExceptionIsolation:
    """A bad on_idle_start/on_idle_end callback must not crash the watcher — the
    next poll has to still get through, not just have the one exception caught
    in isolation."""

    def test_flaky_on_idle_start_is_swallowed_and_polling_continues(self, monkeypatch):
        watcher = IdleWatcher(
            on_idle_start=lambda stopped_at: (_ for _ in ()).throw(RuntimeError("boom")),
            on_idle_end=lambda: None,
            idle_threshold_seconds=THRESHOLD,
        )
        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: THRESHOLD + 10)

        watcher._poll()  # on_idle_start raises — must not propagate

        assert watcher._is_idle is True  # state still advanced despite the raise

        # a later poll (idle ends) proves the watcher is still alive and dispatching
        idle_end_calls = []
        watcher._on_idle_end = lambda: idle_end_calls.append(None)
        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: 0.1)
        watcher._poll()

        assert idle_end_calls == [None]

    def test_flaky_on_idle_end_is_swallowed_and_polling_continues(self, monkeypatch):
        watcher = IdleWatcher(
            on_idle_start=lambda stopped_at: None,
            on_idle_end=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            idle_threshold_seconds=THRESHOLD,
        )
        watcher._is_idle = True
        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: 0.1)

        watcher._poll()  # on_idle_end raises — must not propagate

        assert watcher._is_idle is False  # state still advanced despite the raise

        # a later poll (idle starts again) proves the watcher is still alive
        idle_start_calls = []
        watcher._on_idle_start = idle_start_calls.append
        monkeypatch.setattr(idle_watcher_module, "_seconds_since_last_input", lambda: THRESHOLD + 10)
        watcher._poll()

        assert len(idle_start_calls) == 1
