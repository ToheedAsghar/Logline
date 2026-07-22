"""Regression tests for SessionManager's session-boundary state machine."""

from tracker.session.manager import SessionManager
from tracker.tests.conftest import all_sessions

BUNDLE_ID = "com.example.Foo"
APP_NAME = "Foo"


class TestTitleChangeCarriesIdleFlagForward:
    """The bug: on_title_changed closes the open session and opens a
    replacement with is_idle defaulting to False, silently mislabeling
    ongoing idle time as active whenever a window title changes on its own
    (no real input) while the user is idle."""

    def test_title_change_during_idle_session_inherits_is_idle_true(self, conn):
        manager = SessionManager(conn)
        manager._open_session(
            bundle_id=BUNDLE_ID,
            app_name=APP_NAME,
            window_title="a.txt",
            is_idle=True,
        )
        original_id = manager._open.id

        manager.on_title_changed(bundle_id=BUNDLE_ID, app_name=APP_NAME, window_title="b.txt")

        assert manager._open is not None
        assert manager._open.id != original_id
        assert manager._open.is_idle is True

        sessions = all_sessions(conn)
        assert len(sessions) == 1
        closed = sessions[0]
        assert closed["id"] == original_id
        assert closed["end_reason"] == "title_change"
        assert closed["is_idle"] == 1

    def test_title_change_during_normal_session_stays_non_idle(self, conn):
        """Normal case, unchanged: a genuine non-idle title change still
        produces a non-idle replacement session."""
        manager = SessionManager(conn)
        manager._open_session(
            bundle_id=BUNDLE_ID,
            app_name=APP_NAME,
            window_title="a.txt",
            is_idle=False,
        )
        original_id = manager._open.id

        manager.on_title_changed(bundle_id=BUNDLE_ID, app_name=APP_NAME, window_title="b.txt")

        assert manager._open.id != original_id
        assert manager._open.is_idle is False

        sessions = all_sessions(conn)
        assert len(sessions) == 1
        assert sessions[0]["is_idle"] == 0
