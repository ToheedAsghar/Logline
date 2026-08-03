"""The write path must survive values SQLite refuses to store.

The bug this guards against: `json.dumps(ensure_ascii=False)` happily emits a lone surrogate, which sqlite3
then rejects with UnicodeEncodeError at INSERT time — outside `_encode_context`'s try/except. The failing
INSERT aborted `insert_open_session` after its `DELETE FROM open_session` had already run, leaving an
uncommitted transaction on the shared connection and no mirror row to seal after a crash.
"""

import sqlite3

import pytest

from tracker.session.models import Session
from tracker.storage import db
from tracker.tests.conftest import all_sessions

LONE_SURROGATE = "db\ud800.py"


def _session(**kwargs):
    defaults = dict(
        id="s1", bundle_id="com.microsoft.VSCode", app_name="Code", window_title="db.py — logline",
        started_at="2026-07-29T18:00:00", ended_at="2026-07-29T18:05:00", end_reason="switch",
    )
    defaults.update(kwargs)
    return Session(**defaults)


class TestSurrogateSafeEncoding:
    def test_lone_surrogate_encodes_to_something_sqlite_accepts(self):
        encoded = db._encode_context({"active_file": LONE_SURROGATE})
        assert encoded is not None
        encoded.encode("utf-8")  # must not raise

    def test_lone_surrogate_is_preserved_not_dropped(self):
        """Escaping keeps the value; dropping the whole document would lose the branch and project too."""
        detail = {"active_file": LONE_SURROGATE, "git_branch": "main"}
        assert db._decode_context(db._encode_context(detail)) == detail

    def test_surrogate_context_writes_through_to_the_database(self, conn):
        db.close_open_session(conn, _session(context_detail={"active_file": LONE_SURROGATE}))
        rows = all_sessions(conn)
        assert len(rows) == 1
        assert db._decode_context(rows[0]["context_detail"])["active_file"] == LONE_SURROGATE

    def test_readable_unicode_is_still_stored_unescaped(self):
        """Regression guard: the escaping fallback must only trigger on values that actually fail."""
        assert "🎉" in db._encode_context({"project_name": "🎉project"})


class TestFailedWriteLeavesNoOpenTransaction:
    def test_mirror_survives_a_failure_after_its_delete_has_run(self, conn):
        """`insert_open_session` deletes the mirror row before inserting the replacement. A failure between
        the two used to leave the DELETE uncommitted but live on the connection, so the mirror read as empty
        and the next heartbeat commit would have made that permanent — losing the row a crash needs to seal.
        """
        db.insert_open_session(conn, _session(id="keep-me"))

        with pytest.raises(TypeError):
            db.insert_open_session(conn, _session(id="doomed", is_idle=object()))

        assert conn.in_transaction is False
        assert [row["id"] for row in conn.execute("SELECT id FROM open_session")] == ["keep-me"]

    def test_failed_insert_rolls_back_instead_of_stranding_the_delete(self, conn):
        db.insert_open_session(conn, _session(id="keep-me"))

        # bundle_id is NOT NULL in `sessions`, so this INSERT fails after the mirror DELETE would have run.
        with pytest.raises(sqlite3.IntegrityError):
            db.close_open_session(conn, _session(id="bad", bundle_id=None))

        assert conn.in_transaction is False
        surviving = conn.execute("SELECT id FROM open_session").fetchall()
        assert [row["id"] for row in surviving] == ["keep-me"]

    def test_a_later_write_is_unaffected_by_an_earlier_failure(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            db.close_open_session(conn, _session(id="bad", app_name=None))

        db.close_open_session(conn, _session(id="good"))
        assert [row["id"] for row in all_sessions(conn)] == ["good"]
