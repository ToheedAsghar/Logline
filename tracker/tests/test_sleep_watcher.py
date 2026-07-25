"""Regression tests for SleepWatcher's exception isolation."""

from tracker.watchers.sleep_watcher import _PowerObserver


def _make_observer(on_sleep=None, on_wake=None, on_lock=None, on_unlock=None):
    def noop():
        return None
    return _PowerObserver.alloc().initWithCallbacks_(
        (on_sleep or noop, on_wake or noop, on_lock or noop, on_unlock or noop)
    )


class TestExceptionIsolation:
    """A bad sleep/wake/lock/unlock callback must not crash the whole process —
    each handler has to keep dispatching normally afterward."""

    def test_flaky_on_sleep_is_swallowed_and_observer_keeps_working(self):
        calls = []

        def flaky():
            calls.append(1)
            raise RuntimeError("boom")

        observer = _make_observer(on_sleep=flaky)

        observer.willSleep_(None)  # raises inside the callback — must not propagate
        observer.willSleep_(None)  # proves the observer still dispatches afterward

        assert len(calls) == 2

    def test_flaky_on_wake_is_swallowed_and_observer_keeps_working(self):
        calls = []

        def flaky():
            calls.append(1)
            raise RuntimeError("boom")

        observer = _make_observer(on_wake=flaky)

        observer.didWake_(None)
        observer.didWake_(None)

        assert len(calls) == 2

    def test_flaky_on_lock_is_swallowed_and_observer_keeps_working(self):
        calls = []

        def flaky():
            calls.append(1)
            raise RuntimeError("boom")

        observer = _make_observer(on_lock=flaky)

        observer.screenLocked_(None)
        observer.screenLocked_(None)

        assert len(calls) == 2

    def test_flaky_on_unlock_is_swallowed_and_observer_keeps_working(self):
        calls = []

        def flaky():
            calls.append(1)
            raise RuntimeError("boom")

        observer = _make_observer(on_unlock=flaky)

        observer.screenUnlocked_(None)
        observer.screenUnlocked_(None)

        assert len(calls) == 2
