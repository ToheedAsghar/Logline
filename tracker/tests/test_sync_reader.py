"""Reading sessions for upload: read-only enforcement, timezone-correct filtering, and cursor paging.

Two of these are regression guards for bugs that would be invisible in normal use: string-comparing local-offset
timestamps against a UTC checkpoint only misbehaves across offsets, and a timestamp-only cursor only misbehaves
when a batch boundary lands inside a group of sessions sharing one `ended_at`.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tracker.constants import CREATE_OPEN_SESSION, CREATE_SESSIONS, SYNC_OVERLAP_SECONDS
from tracker.sync import reader
from tracker.sync.reader import Cursor

BASE = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)


def _insert(conn, session_id, ended_at, started_at=None, **overrides):
    values = {
        "id": session_id,
        "bundle_id": "com.microsoft.VSCode",
        "app_name": "Code",
        "window_title": "db.py",
        "started_at": started_at or ended_at,
        "ended_at": ended_at,
        "end_reason": "switch",
        "is_idle": 0,
        "project_path": None,
        "context_detail": None,
    }
    values.update(overrides)
    conn.execute(
        "INSERT INTO sessions (id, bundle_id, app_name, window_title, started_at, ended_at, end_reason, is_idle, "
        "project_path, context_detail) VALUES (:id, :bundle_id, :app_name, :window_title, :started_at, :ended_at, "
        ":end_reason, :is_idle, :project_path, :context_detail)",
        values,
    )
    conn.commit()


@pytest.fixture
def db_file(tmp_path):
    """A real on-disk database, since read-only mode cannot be exercised against `:memory:`."""
    path = tmp_path / "tracker.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE_SESSIONS)
    conn.execute(CREATE_OPEN_SESSION)
    conn.commit()
    yield path, conn
    conn.close()


class TestReadOnlyConnection:
    def test_writes_are_refused(self, db_file):
        path, writable = db_file
        _insert(writable, "s1", BASE.isoformat())

        conn = reader.open_read_only(path)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("DELETE FROM sessions")
        finally:
            conn.close()

    def test_reads_work_while_the_capture_daemon_holds_the_file(self, db_file):
        """WAL is the tracker's journal mode; a read-only connection must still work against it."""
        path, writable = db_file
        writable.execute("PRAGMA journal_mode=WAL")
        _insert(writable, "s1", BASE.isoformat())

        conn = reader.open_read_only(path)
        try:
            assert len(reader.fetch_batch(conn, Cursor(ended_at=reader.EPOCH.isoformat()), 10)) == 1
        finally:
            conn.close()

    def test_missing_database_is_not_created(self, tmp_path):
        with pytest.raises(sqlite3.OperationalError):
            reader.open_read_only(tmp_path / "absent.db")
        assert not (tmp_path / "absent.db").exists()


class TestTimezoneCorrectness:
    def test_local_offset_rows_compare_against_a_utc_checkpoint(self, conn):
        """`2026-08-06T13:00:00+05:00` is 08:00 UTC — before a 09:00 UTC checkpoint, though it sorts after it
        as a string. Comparing as text would upload it again forever, or skip newer rows."""
        _insert(conn, "before", "2026-08-06T13:00:00+05:00")
        _insert(conn, "after", "2026-08-06T15:00:00+05:00")

        sessions = reader.fetch_batch(conn, Cursor(ended_at=BASE.isoformat()), 10)

        assert [s.id for s in sessions] == ["after"]

    def test_ordering_is_by_absolute_time_not_string(self, conn):
        _insert(conn, "second", "2026-08-06T11:00:00+00:00")
        _insert(conn, "first", "2026-08-06T15:30:00+05:00")

        sessions = reader.fetch_batch(conn, Cursor(ended_at=reader.EPOCH.isoformat()), 10)

        assert [s.id for s in sessions] == ["first", "second"]


class TestCursorPaging:
    def test_batch_is_limited_and_resumes_without_gaps(self, conn):
        for index in range(5):
            _insert(conn, f"s{index}", (BASE + timedelta(minutes=index)).isoformat())

        cursor = Cursor(ended_at=reader.EPOCH.isoformat())
        seen = []
        while True:
            batch = reader.fetch_batch(conn, cursor, 2)
            if not batch:
                break
            seen.extend(s.id for s in batch)
            cursor = reader.advance(batch)

        assert seen == ["s0", "s1", "s2", "s3", "s4"]

    def test_sessions_sharing_one_timestamp_are_not_skipped_at_a_batch_boundary(self, conn):
        """All three end in the same second, and the batch splits them. A timestamp-only cursor would either drop
        the tail or re-read the same batch forever."""
        same_moment = BASE.isoformat()
        for session_id in ("a", "b", "c"):
            _insert(conn, session_id, same_moment)

        cursor = Cursor(ended_at=reader.EPOCH.isoformat())
        seen = []
        for _ in range(5):
            batch = reader.fetch_batch(conn, cursor, 2)
            if not batch:
                break
            seen.extend(s.id for s in batch)
            cursor = reader.advance(batch)

        assert seen == ["a", "b", "c"]

    def test_open_sessions_are_never_read(self, conn):
        """In-progress work lives in `open_session` until it ends, so it cannot be uploaded early."""
        conn.execute(
            "INSERT INTO open_session (id, bundle_id, app_name, window_title, started_at, ended_at, is_idle) "
            "VALUES ('open', 'com.apple.Terminal', 'Terminal', NULL, ?, ?, 0)",
            (BASE.isoformat(), (BASE + timedelta(minutes=1)).isoformat()),
        )
        conn.commit()

        assert reader.fetch_batch(conn, Cursor(ended_at=reader.EPOCH.isoformat()), 10) == []


class TestCheckpointConversion:
    def test_no_checkpoint_starts_at_the_epoch(self):
        assert reader.cursor_from_checkpoint(None) == Cursor(ended_at=reader.EPOCH.isoformat())

    def test_checkpoint_is_rewound_by_the_overlap_window(self):
        cursor = reader.cursor_from_checkpoint(BASE)

        assert datetime.fromisoformat(cursor.ended_at) == BASE - timedelta(seconds=SYNC_OVERLAP_SECONDS)
        assert cursor.session_id is None

    def test_overlap_re_sends_sessions_inside_the_window(self, conn):
        """Covers clock drift: a session the server timestamped slightly ahead of this machine still gets another
        chance to be sent."""
        inside = BASE - timedelta(seconds=SYNC_OVERLAP_SECONDS // 2)
        outside = BASE - timedelta(seconds=SYNC_OVERLAP_SECONDS * 2)
        _insert(conn, "inside-window", inside.isoformat())
        _insert(conn, "outside-window", outside.isoformat())

        cursor = reader.cursor_from_checkpoint(BASE)

        assert [s.id for s in reader.fetch_batch(conn, cursor, 10)] == ["inside-window"]

    def test_window_still_covers_the_backends_clock_skew_tolerance(self):
        """Guards against tuning the window down to nothing: the backend rejects sessions more than
        CLOCK_SKEW_TOLERANCE_MINUTES (5) in the future, so anything below that would drop real rows on a machine
        whose clock runs ahead."""
        assert SYNC_OVERLAP_SECONDS >= 5 * 60
