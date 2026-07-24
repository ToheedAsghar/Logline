"""Regression tests for SessionManager's session-boundary state machine."""

from datetime import datetime

from tracker.session.manager import SessionManager
from tracker.tests.conftest import all_sessions, open_session_rows

BUNDLE_ID = "com.example.Foo"
APP_NAME = "Foo"


class TestBackdatingClampAvoidsDuplicateZeroDurationRow:
    """When an idle poll's computed stopped_at predates the currently-open
    session's own started_at (the session itself was only opened *during* the
    idle span, e.g. by a title change that fired with no real input), closing
    and reopening with that backdated timestamp would produce a session whose
    ended_at is before its started_at — a negative/zero-duration duplicate
    row. The fix relabels the existing open session as idle in place instead
    of closing/reopening it."""

    def test_stopped_at_before_session_open_relabels_in_place(self, conn):
        manager = SessionManager(conn)
        manager._open_session(
            bundle_id=BUNDLE_ID,
            app_name=APP_NAME,
            window_title="doc.txt",
            started_at="2026-07-22T10:05:00-04:00",
        )
        original_id = manager._open.id

        manager.on_idle_start(datetime.fromisoformat("2026-07-22T10:04:00-04:00"))

        assert manager._open is not None
        assert manager._open.id == original_id
        assert manager._open.is_idle is True
        assert manager._open.started_at == "2026-07-22T10:05:00-04:00"
        assert all_sessions(conn) == []
        assert len(open_session_rows(conn)) == 1
        assert open_session_rows(conn)[0]["id"] == original_id

    def test_stopped_at_equal_to_open_time_also_relabels_in_place(self, conn):
        manager = SessionManager(conn)
        manager._open_session(
            bundle_id=BUNDLE_ID,
            app_name=APP_NAME,
            started_at="2026-07-22T10:05:00-04:00",
        )
        original_id = manager._open.id

        manager.on_idle_start(datetime.fromisoformat("2026-07-22T10:05:00-04:00"))

        assert manager._open.id == original_id
        assert manager._open.is_idle is True
        assert all_sessions(conn) == []

    def test_stopped_at_after_session_open_still_closes_and_backdates_normally(self, conn):
        """Regression guard: the clamp must not swallow the ordinary case where
        input genuinely stopped partway through the open session's life."""
        manager = SessionManager(conn)
        manager._open_session(
            bundle_id=BUNDLE_ID,
            app_name=APP_NAME,
            window_title="doc.txt",
            started_at="2026-07-22T10:00:00-04:00",
        )
        original_id = manager._open.id

        manager.on_idle_start(datetime.fromisoformat("2026-07-22T10:03:00-04:00"))

        assert manager._open.id != original_id
        assert manager._open.is_idle is True
        assert manager._open.started_at == "2026-07-22T10:03:00-04:00"

        sessions = all_sessions(conn)
        assert len(sessions) == 1
        closed = sessions[0]
        assert closed["id"] == original_id
        assert closed["ended_at"] == "2026-07-22T10:03:00-04:00"
        assert closed["end_reason"] == "idle"
        assert closed["is_idle"] == 0

        open_rows = open_session_rows(conn)
        assert len(open_rows) == 1
        assert open_rows[0]["id"] == manager._open.id


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


class TestCrashRecoveryPreservesIdleState:
    """When the tracker crashes during idle time, seal_dangling_session() must
    read is_idle from open_session and seal the session as idle (is_idle=1),
    not active work."""

    def test_crashed_idle_session_seals_as_idle(self, conn):
        manager1 = SessionManager(conn)
        manager1._open_session(
            bundle_id=BUNDLE_ID,
            app_name=APP_NAME,
            window_title="doc.txt",
            is_idle=True,
        )
        assert len(open_session_rows(conn)) == 1
        assert open_session_rows(conn)[0]["is_idle"] == 1

        # Simulate process restart after crash/unclean exit
        manager2 = SessionManager(conn)

        sessions = all_sessions(conn)
        assert len(sessions) == 1
        sealed = sessions[0]
        assert sealed["is_idle"] == 1
        assert sealed["end_reason"] == "quit"

    def test_crashed_active_session_seals_as_active(self, conn):
        manager1 = SessionManager(conn)
        manager1._open_session(
            bundle_id=BUNDLE_ID,
            app_name=APP_NAME,
            window_title="doc.txt",
            is_idle=False,
        )
        assert open_session_rows(conn)[0]["is_idle"] == 0

        manager2 = SessionManager(conn)

        sessions = all_sessions(conn)
        assert len(sessions) == 1
        sealed = sessions[0]
        assert sealed["is_idle"] == 0
        assert sealed["end_reason"] == "quit"

