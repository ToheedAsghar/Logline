"""Forward-migration tests for the ad-hoc PRAGMA guard.

The tracker has no migration framework, so an existing database file on disk must survive a schema change on
the next start. `test_migrates_real_database_copy` runs against a copy of the developer's actual tracker.db
when one exists — a fresh empty database would not catch a pre-existing-data failure.
"""

import shutil
import sqlite3

import pytest

from tracker.constants import CONTEXT_COLUMNS, DB_PATH
from tracker.session.models import Session
from tracker.storage import db

LEGACY_SESSIONS = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, bundle_id TEXT NOT NULL, app_name TEXT NOT NULL, window_title TEXT,
    started_at TEXT NOT NULL, ended_at TEXT NOT NULL, end_reason TEXT NOT NULL,
    is_idle INTEGER NOT NULL DEFAULT 0
)
"""

LEGACY_OPEN_SESSION = """
CREATE TABLE open_session (
    id TEXT PRIMARY KEY, bundle_id TEXT, app_name TEXT, window_title TEXT,
    started_at TEXT, ended_at TEXT
)
"""


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    db._add_missing_columns(conn, "open_session", (("is_idle", "INTEGER NOT NULL DEFAULT 0"),) + CONTEXT_COLUMNS)
    db._add_missing_columns(conn, "sessions", CONTEXT_COLUMNS)
    conn.commit()


class TestForwardMigration:
    def test_adds_columns_to_legacy_database(self, tmp_path):
        path = tmp_path / "legacy.db"
        conn = _open(path)
        conn.execute(LEGACY_SESSIONS)
        conn.execute(LEGACY_OPEN_SESSION)
        conn.execute(
            "INSERT INTO sessions VALUES ('a','com.apple.Notes','Notes','t','2026-01-01','2026-01-01','switch',0)"
        )
        conn.commit()

        _migrate(conn)

        assert {"project_path", "context_detail"} <= _columns(conn, "sessions")
        assert {"is_idle", "project_path", "context_detail"} <= _columns(conn, "open_session")
        row = conn.execute("SELECT * FROM sessions WHERE id='a'").fetchone()
        assert row["project_path"] is None and row["context_detail"] is None
        assert row["window_title"] == "t"

    def test_migration_is_idempotent(self, tmp_path):
        path = tmp_path / "twice.db"
        conn = _open(path)
        conn.execute(LEGACY_SESSIONS)
        conn.execute(LEGACY_OPEN_SESSION)
        conn.commit()
        _migrate(conn)
        _migrate(conn)
        assert len(_columns(conn, "sessions")) == 10

    def test_seal_dangling_reads_legacy_row_without_new_columns(self, tmp_path):
        """A row written by the previous build has no context columns; sealing it must not KeyError."""
        path = tmp_path / "dangling.db"
        conn = _open(path)
        conn.execute(LEGACY_SESSIONS)
        conn.execute(LEGACY_OPEN_SESSION)
        conn.execute("INSERT INTO open_session VALUES ('x','com.apple.Notes','Notes','t','2026-01-01','2026-01-01')")
        conn.commit()
        _migrate(conn)

        sealed = db.seal_dangling_session(conn)
        assert sealed is not None
        assert sealed.end_reason == "quit"
        assert sealed.project_path is None and sealed.context_detail is None

    @pytest.mark.skipif(not DB_PATH.exists(), reason="no real tracker.db on this machine")
    def test_migrates_real_database_copy(self, tmp_path):
        """Runs the migration against a copy of the live database, with its real accumulated rows."""
        copy = tmp_path / "real.db"
        shutil.copy(DB_PATH, copy)
        conn = _open(copy)
        before = conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
        non_null_before = (
            conn.execute("SELECT COUNT(*) c FROM sessions WHERE project_path IS NOT NULL").fetchone()["c"]
            if "project_path" in _columns(conn, "sessions")
            else 0
        )

        _migrate(conn)

        assert {"project_path", "context_detail"} <= _columns(conn, "sessions")
        assert conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] == before
        assert (
            conn.execute("SELECT COUNT(*) c FROM sessions WHERE project_path IS NOT NULL").fetchone()["c"]
            == non_null_before
        )

        session = Session(
            id="new-row", bundle_id="com.microsoft.VSCode", app_name="Code", window_title="db.py — logline",
            started_at="2026-07-29T18:00:00", ended_at="2026-07-29T18:05:00", end_reason="switch",
            project_path="/Users/x/logline", context_detail={"git_branch": "main", "active_file": "db.py"},
        )
        db.close_open_session(conn, session)
        row = conn.execute("SELECT * FROM sessions WHERE id='new-row'").fetchone()
        assert row["project_path"] == "/Users/x/logline"
        assert db._decode_context(row["context_detail"])["git_branch"] == "main"


class TestContextEncoding:
    def test_empty_context_stored_as_null(self):
        assert db._encode_context({}) is None
        assert db._encode_context(None) is None

    def test_roundtrip(self):
        detail = {"git_branch": "main", "is_meeting": True}
        assert db._decode_context(db._encode_context(detail)) == detail

    def test_unserializable_context_degrades_to_null(self):
        assert db._encode_context({"bad": object()}) is None

    def test_corrupt_json_decodes_to_none(self):
        assert db._decode_context("{not json") is None
        assert db._decode_context("[1,2]") is None
