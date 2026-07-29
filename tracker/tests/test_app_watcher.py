"""Regression tests for AppWatcher's exception isolation and nullable-field guards."""

import sqlite3

import pytest
from AppKit import NSWorkspaceApplicationKey

from tracker.constants import CREATE_OPEN_SESSION, CREATE_SESSIONS
from tracker.session.manager import SessionManager
from tracker.watchers.app_watcher import _ActivationObserver


class _FakeApp:
    def __init__(self, bundle_id, name):
        self.bundle_id = bundle_id
        self._name = name

    def bundleIdentifier(self):
        return self.bundle_id

    def localizedName(self):
        return self._name


class _FakeNotification:
    """Stands in for the real NSNotification — appActivated_ only ever calls
    .userInfo() on it, so a plain object is enough."""

    def __init__(self, user_info):
        self._user_info = user_info

    def userInfo(self):
        return self._user_info


def _make_observer(callback):
    return _ActivationObserver.alloc().initWithCallback_(callback)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(CREATE_SESSIONS)
    connection.execute(CREATE_OPEN_SESSION)
    connection.commit()
    yield connection
    connection.close()


class TestExceptionIsolation:
    """If one thing goes wrong while checking a window title, the tracker
    should NOT stop working completely.

    This test makes a fake title-checker that fails on purpose the first
    time it runs, then works fine after that. We check the title twice in a
    row. If the tracker handled the first failure correctly, the second
    check should still go through normally. If it didn't, the second check
    would never happen at all."""

    def test_callback_exception_is_swallowed_and_watcher_keeps_dispatching(self):
        calls = []

        def flaky_callback(bundle_id, app_name):
            calls.append((bundle_id, app_name))
            if len(calls) == 1:
                raise RuntimeError("boom")

        observer = _make_observer(flaky_callback)
        notification = _FakeNotification({NSWorkspaceApplicationKey: _FakeApp("com.example.Foo", "Foo")})

        observer.appActivated_(notification)  # raises inside the callback — must not propagate
        observer.appActivated_(notification)  # proves the observer is still alive afterward

        assert len(calls) == 2


class TestGuardsMissingUserInfo:
    """A malformed notification (missing key, or no userInfo at all) must be a
    no-op, not a crash."""

    def test_missing_expected_key_does_not_crash_and_skips_callback(self):
        calls = []
        observer = _make_observer(lambda bundle_id, app_name: calls.append((bundle_id, app_name)))
        notification = _FakeNotification({})

        observer.appActivated_(notification)

        assert calls == []

    def test_none_user_info_does_not_crash_and_skips_callback(self):
        calls = []
        observer = _make_observer(lambda bundle_id, app_name: calls.append((bundle_id, app_name)))
        notification = _FakeNotification(None)

        observer.appActivated_(notification)

        assert calls == []


class TestCoalescesNullableFields:
    """bundle_id/app_name must never reach the callback as None — SessionManager
    and storage both assume real strings."""

    def test_none_bundle_id_and_app_name_coalesce_to_placeholders(self):
        calls = []
        observer = _make_observer(lambda bundle_id, app_name: calls.append((bundle_id, app_name)))
        notification = _FakeNotification({NSWorkspaceApplicationKey: _FakeApp(None, None)})

        observer.appActivated_(notification)

        assert calls == [("unknown", "Unknown")]

    def test_coalesced_values_dont_crash_on_session_close(self, conn):
        """This guards against bundle_id=None being accepted while the session is
        still open, then failing with sqlite3.IntegrityError when it is closed
        into `sessions`, which requires bundle_id and app_name."""
        manager = SessionManager(conn)
        observer = _make_observer(manager.on_app_activated)

        notification = _FakeNotification({NSWorkspaceApplicationKey: _FakeApp(None, None)})
        observer.appActivated_(notification)  # opens a session with coalesced fields

        next_notification = _FakeNotification(
            {NSWorkspaceApplicationKey: _FakeApp("com.example.Bar", "Bar")}
        )
        observer.appActivated_(next_notification)  # closes the first session — must not raise

        assert manager._open.bundle_id == "com.example.Bar"
