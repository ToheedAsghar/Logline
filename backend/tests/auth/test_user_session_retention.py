"""Tests for `app/auth/retention.py` and the `scripts/purge_user_sessions.py` runner that drives it.

The property that matters most here is what the purge must NOT remove: a revoked-but-unexpired row is the
tripwire `crud.rotate_session` needs to recognise a replayed refresh token as reuse. Deleting one early would
downgrade a detectable theft into an ordinary "unknown token" 401, so several tests below pin rows that are
revoked, or expired only recently, as untouchable.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

import pytest
from scripts.purge_user_sessions import PURGE_ADVISORY_LOCK_KEY
from scripts.purge_user_sessions import main as purge_main
from sqlalchemy import text

from app.auth import crud
from app.auth.constants import SESSION_RETENTION_WINDOW_DAYS
from app.auth.models import User, UserSession
from app.auth.retention import count_purgeable_sessions, purge_expired_sessions
from app.db.session import SessionLocal

TEST_EMAIL = "session-retention-test@example.com"


@pytest.fixture
def user_id():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == TEST_EMAIL).first()
        if existing is not None:
            db.query(UserSession).filter(UserSession.user_id == existing.id).delete()
            db.query(User).filter(User.id == existing.id).delete()
            db.commit()

        user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        uid = user.id
    finally:
        db.close()

    yield uid

    db = SessionLocal()
    try:
        db.query(UserSession).filter(UserSession.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()
    finally:
        db.close()


def _make_session(user_id: int, *, expired_days_ago: float, revoked: bool = False) -> int:
    """Create a session row whose `expires_at` is `expired_days_ago` days in the past (negative for the future)."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        session = UserSession(
            user_id=user_id,
            family_id=0,
            refresh_token_hash=f"retention-test-{now.timestamp()}-{expired_days_ago}-{revoked}",
            expires_at=now - timedelta(days=expired_days_ago),
            revoked_at=now if revoked else None,
        )
        db.add(session)
        db.flush()
        session.family_id = session.id
        db.commit()
        return session.id
    finally:
        db.close()


def _exists(session_id: int) -> bool:
    db = SessionLocal()
    try:
        return db.query(UserSession).filter(UserSession.id == session_id).first() is not None
    finally:
        db.close()


def _count_for_user(user_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(UserSession).filter(UserSession.user_id == user_id).count()
    finally:
        db.close()


class TestPurgeExpiredSessions:
    def test_deletes_rows_expired_beyond_the_retention_window(self, user_id):
        doomed = _make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS + 1)

        db = SessionLocal()
        try:
            assert purge_expired_sessions(db) >= 1
        finally:
            db.close()

        assert not _exists(doomed)

    def test_keeps_rows_that_expired_inside_the_retention_window(self, user_id):
        recent = _make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS - 1)

        db = SessionLocal()
        try:
            purge_expired_sessions(db)
        finally:
            db.close()

        assert _exists(recent)

    def test_keeps_live_unexpired_rows(self, user_id):
        live = _make_session(user_id, expired_days_ago=-1)

        db = SessionLocal()
        try:
            purge_expired_sessions(db)
        finally:
            db.close()

        assert _exists(live)

    def test_keeps_a_revoked_row_that_has_not_expired(self, user_id):
        """The reuse-detection tripwire. Revocation happens on every rotation, so if revoked rows were purged on
        revocation this row would vanish immediately -- and a replay of its token would look merely unknown."""
        revoked_but_live = _make_session(user_id, expired_days_ago=-1, revoked=True)

        db = SessionLocal()
        try:
            purge_expired_sessions(db)
        finally:
            db.close()

        assert _exists(revoked_but_live)

    def test_a_row_can_never_be_purged_while_its_token_is_still_presentable(self, user_id):
        """`expires_at` alone decides both questions -- whether rotation refuses a token and whether retention may
        delete its row -- and retention additionally waits a full window past that point. So there is no reachable
        state where a token still passes rotation's expiry check but its row has already been purged."""
        still_usable = _make_session(user_id, expired_days_ago=-1, revoked=False)
        just_expired = _make_session(user_id, expired_days_ago=0.001)

        db = SessionLocal()
        try:
            purge_expired_sessions(db)
        finally:
            db.close()

        assert _exists(still_usable)
        assert _exists(just_expired)

    def test_deletes_across_multiple_batches(self, user_id):
        ids = [_make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS + 2) for _ in range(5)]

        db = SessionLocal()
        try:
            deleted = purge_expired_sessions(db, batch_size=2)
        finally:
            db.close()

        assert deleted >= 5
        assert not any(_exists(i) for i in ids)

    def test_returns_zero_and_deletes_nothing_when_there_is_nothing_to_purge(self, user_id):
        live = _make_session(user_id, expired_days_ago=-1)

        db = SessionLocal()
        try:
            purge_expired_sessions(db)
            assert purge_expired_sessions(db) == 0
        finally:
            db.close()

        assert _exists(live)

    def test_count_purgeable_does_not_delete(self, user_id):
        doomed = _make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS + 1)

        db = SessionLocal()
        try:
            assert count_purgeable_sessions(db) >= 1
        finally:
            db.close()

        assert _exists(doomed)

    def test_rotation_still_rejects_a_replay_whose_row_survived_the_purge(self, user_id):
        """End-to-end version of the constraint: rotate, purge, then replay. The purge must leave reuse detection
        able to do its job."""
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            first_session_id = first_session.id
            crud.rotate_session(db, refresh_token=stale_token)
            purge_expired_sessions(db)
        finally:
            db.close()

        assert _exists(first_session_id)

        db = SessionLocal()
        try:
            assert crud.rotate_session(db, refresh_token=stale_token).outcome is not crud.RotationOutcome.ROTATED
        finally:
            db.close()


class TestPurgeScript:
    def test_dry_run_reports_without_deleting(self, user_id, caplog):
        doomed = _make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS + 1)

        with caplog.at_level(logging.INFO, logger="scripts.purge_user_sessions"):
            assert purge_main(["--dry-run"]) == 0

        assert _exists(doomed)
        assert any("dry run" in r.getMessage() for r in caplog.records)

    def test_real_run_deletes_and_logs_the_row_count(self, user_id, caplog):
        doomed = _make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS + 1)

        with caplog.at_level(logging.INFO, logger="scripts.purge_user_sessions"):
            assert purge_main([]) == 0

        assert not _exists(doomed)
        assert any("rows deleted" in r.getMessage() for r in caplog.records)

    def test_second_concurrent_run_no_ops_instead_of_racing(self, user_id):
        """A duplicated cron entry or a second app instance must not run two purges at once. The advisory lock is
        held for the whole run, so the loser exits non-zero having deleted nothing, rather than interleaving
        batch deletes with the winner.
        """
        _make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS + 1)

        blocker = SessionLocal()
        exit_codes = []
        try:
            held = blocker.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY}
            ).scalar()
            assert held is True

            thread = threading.Thread(target=lambda: exit_codes.append(purge_main([])))
            thread.start()
            thread.join(timeout=10)
            assert not thread.is_alive(), "purge blocked waiting on the lock instead of exiting immediately"
        finally:
            blocker.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY})
            blocker.commit()
            blocker.close()

        assert exit_codes == [1]
        assert _count_for_user(user_id) == 1

    def test_runs_normally_once_the_lock_is_free_again(self, user_id):
        doomed = _make_session(user_id, expired_days_ago=SESSION_RETENTION_WINDOW_DAYS + 1)

        assert purge_main([]) == 0
        assert purge_main([]) == 0
        assert not _exists(doomed)

    @pytest.mark.parametrize("batch_size", ["0", "-1"])
    def test_rejects_a_batch_size_below_one(self, batch_size):
        """A `LIMIT 0` batch never shrinks below the batch size, so the delete loop would spin forever while
        holding the advisory lock, locking out every legitimate run behind it."""
        with pytest.raises(SystemExit):
            purge_main(["--batch-size", batch_size])
