"""Tests for the refresh-token session primitives added in
`app/auth/{models,crud,routers}.py`: `UserSession` creation at login,
`/auth/refresh`'s atomic rotate-on-use, `/auth/logout`, and
`/auth/logout-all`.

Covers the corner cases called out during design: replay of an already-
rotated token, replay of a revoked/expired token, and two concurrent
requests racing to consume the same refresh token (mirrors
`test_reset_password.py::TestResetPasswordConcurrency`, same atomic-claim
pattern).

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient

from app.auth import crud
from app.auth.constants import REFRESH_REUSE_GRACE_SECONDS, REFRESH_TOKEN_COOKIE_NAME, REFRESH_TOKEN_COOKIE_PATH
from app.auth.models import User, UserSession
from app.auth.routers import logout, logout_all, refresh
from app.auth.security import decode_access_token
from app.config import settings
from app.db.session import SessionLocal
from app.main import app

TEST_EMAIL = "user-sessions-test@example.com"
OTHER_EMAIL = "user-sessions-test-other@example.com"


def _make_user(db, email: str) -> int:
    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        db.query(UserSession).filter(UserSession.user_id == user.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()

    user = User(email=email, hashed_password="not-a-real-hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _cleanup_user(db, user_id: int) -> None:
    db.query(UserSession).filter(UserSession.user_id == user_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()


@pytest.fixture
def user_id():
    db = SessionLocal()
    try:
        uid = _make_user(db, TEST_EMAIL)
    finally:
        db.close()

    yield uid

    db = SessionLocal()
    try:
        _cleanup_user(db, uid)
    finally:
        db.close()


@pytest.fixture
def other_user_id():
    db = SessionLocal()
    try:
        uid = _make_user(db, OTHER_EMAIL)
    finally:
        db.close()

    yield uid

    db = SessionLocal()
    try:
        _cleanup_user(db, uid)
    finally:
        db.close()


def _reload_session(session_id: int) -> UserSession:
    db = SessionLocal()
    try:
        return db.query(UserSession).filter(UserSession.id == session_id).first()
    finally:
        db.close()


def _live_sessions_in_family(family_id: int) -> int:
    db = SessionLocal()
    try:
        return (
            db.query(UserSession)
            .filter(UserSession.family_id == family_id, UserSession.revoked_at.is_(None))
            .count()
        )
    finally:
        db.close()


def _set_revoked_at(session_id: int, revoked_at: datetime) -> None:
    db = SessionLocal()
    try:
        db.query(UserSession).filter(UserSession.id == session_id).update({"revoked_at": revoked_at})
        db.commit()
    finally:
        db.close()


def _expire_session(session_id: int) -> None:
    db = SessionLocal()
    try:
        db.query(UserSession).filter(UserSession.id == session_id).update(
            {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}
        )
        db.commit()
    finally:
        db.close()


def _age_revocations_beyond_grace(user_id: int) -> None:
    """Backdate every revocation this user has, so an immediately-following replay reads as reuse rather than as
    a concurrent refresh. Cheaper and far more reliable than sleeping out the real grace window in a test."""
    db = SessionLocal()
    try:
        stale = datetime.now(timezone.utc) - timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS + 60)
        db.query(UserSession).filter(
            UserSession.user_id == user_id, UserSession.revoked_at.is_not(None)
        ).update({"revoked_at": stale})
        db.commit()
    finally:
        db.close()


class TestCreateSession:
    def test_family_id_equals_its_own_row_id(self, user_id):
        db = SessionLocal()
        try:
            session, token = crud.create_session(db, user_id=user_id)
            assert session.family_id == session.id
            assert token
        finally:
            db.close()

    def test_hash_stored_not_raw_token(self, user_id):
        db = SessionLocal()
        try:
            session, token = crud.create_session(db, user_id=user_id)
            assert session.refresh_token_hash != token
            assert token not in session.refresh_token_hash
        finally:
            db.close()

    def test_expires_at_matches_configured_lifetime(self, user_id):
        db = SessionLocal()
        try:
            before = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
            session, _ = crud.create_session(db, user_id=user_id)
            after = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
            assert before - timedelta(seconds=5) <= session.expires_at <= after + timedelta(seconds=5)
        finally:
            db.close()


class TestRotateSession:
    def test_valid_token_rotates_and_returns_new_token(self, user_id):
        db = SessionLocal()
        try:
            old_session, old_token = crud.create_session(db, user_id=user_id)

            result = crud.rotate_session(db, refresh_token=old_token)

            assert result.outcome is crud.RotationOutcome.ROTATED
            assert result.token != old_token
            assert result.session.id != old_session.id
        finally:
            db.close()

    def test_rotation_revokes_the_old_row_and_sets_last_used_at(self, user_id):
        db = SessionLocal()
        try:
            old_session, old_token = crud.create_session(db, user_id=user_id)
            old_session_id = old_session.id
            crud.rotate_session(db, refresh_token=old_token)
        finally:
            db.close()

        reloaded = _reload_session(old_session_id)
        assert reloaded.revoked_at is not None
        assert reloaded.last_used_at is not None

    def test_new_row_inherits_the_same_family_id(self, user_id):
        db = SessionLocal()
        try:
            old_session, old_token = crud.create_session(db, user_id=user_id)
            new_session = crud.rotate_session(db, refresh_token=old_token).session
            assert new_session.family_id == old_session.family_id
            assert new_session.family_id == old_session.id
        finally:
            db.close()

    def test_chained_rotations_keep_the_same_family_id(self, user_id):
        db = SessionLocal()
        try:
            session, token = crud.create_session(db, user_id=user_id)
            original_family_id = session.family_id

            for _ in range(3):
                result = crud.rotate_session(db, refresh_token=token)
                session, token = result.session, result.token
                assert session.family_id == original_family_id
        finally:
            db.close()

    def test_replaying_an_already_rotated_token_fails(self, user_id):
        """The defining reuse case: once a refresh token has been rotated away, presenting the same raw token
        again must never succeed -- even though the row it originally named still exists (now revoked)."""
        db = SessionLocal()
        try:
            _, old_token = crud.create_session(db, user_id=user_id)
            crud.rotate_session(db, refresh_token=old_token)

            replay_result = crud.rotate_session(db, refresh_token=old_token)

            assert replay_result.outcome is not crud.RotationOutcome.ROTATED
        finally:
            db.close()

    def test_expired_token_is_rejected(self, user_id):
        db = SessionLocal()
        try:
            session, token = crud.create_session(db, user_id=user_id)
            db.query(UserSession).filter(UserSession.id == session.id).update(
                {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
            )
            db.commit()

            result = crud.rotate_session(db, refresh_token=token)

            assert result.outcome is crud.RotationOutcome.REJECTED
        finally:
            db.close()

    def test_revoked_token_is_rejected(self, user_id):
        """Revoked well outside the reuse grace window, so this is the hard-rejection path rather than the
        benign concurrent-refresh one covered in `TestRefreshTokenReuseDetection`."""
        db = SessionLocal()
        try:
            session, token = crud.create_session(db, user_id=user_id)
            db.query(UserSession).filter(UserSession.id == session.id).update(
                {"revoked_at": datetime.now(timezone.utc) - timedelta(hours=1)}
            )
            db.commit()

            result = crud.rotate_session(db, refresh_token=token)

            assert result.outcome is crud.RotationOutcome.REJECTED
        finally:
            db.close()

    def test_unknown_token_is_rejected(self, user_id):
        db = SessionLocal()
        try:
            result = crud.rotate_session(db, refresh_token="not-a-real-token")
            assert result.outcome is crud.RotationOutcome.REJECTED
        finally:
            db.close()

    def test_concurrent_rotation_of_the_same_token_only_one_succeeds(self, user_id):
        """Two near-simultaneous refresh requests presenting the same valid refresh token, each on its own DB
        session/connection (mirrors two real concurrent HTTP requests). Exactly one must win; the other must be
        treated as an invalid token, never both succeeding and never a crash.
        """
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)
        finally:
            db.close()

        results = {}

        def attempt(name):
            thread_db = SessionLocal()
            try:
                results[name] = crud.rotate_session(thread_db, refresh_token=token)
            finally:
                thread_db.close()

        t1 = threading.Thread(target=attempt, args=("a",))
        t2 = threading.Thread(target=attempt, args=("b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        outcomes = [r.outcome for r in results.values()]
        assert outcomes.count(crud.RotationOutcome.ROTATED) == 1, f"expected exactly one success, got {results}"
        assert outcomes.count(crud.RotationOutcome.CONCURRENT_ROTATION) == 1, (
            f"expected the loser to be classed a benign concurrent refresh, not reuse, got {results}"
        )


class TestRefreshEndpoint:
    def test_valid_cookie_returns_a_working_access_token(self, user_id):
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)

            result = refresh(response=Response(), refresh_token=token, db=db)

            assert decode_access_token(result.access_token) == user_id
        finally:
            db.close()

    def test_missing_cookie_returns_401(self, user_id):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                refresh(response=Response(), refresh_token=None, db=db)
            assert exc_info.value.status_code == 401
        finally:
            db.close()

    def test_unknown_cookie_returns_401(self, user_id):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                refresh(response=Response(), refresh_token="not-a-real-token", db=db)
            assert exc_info.value.status_code == 401
        finally:
            db.close()

    def test_replayed_rotated_cookie_within_grace_returns_409(self, user_id):
        """Replayed immediately after rotation -- within the grace window -- so this is the benign concurrent-tab
        path, not reuse. `TestRefreshEndpointClearsCookieOnFailure` covers the aged-past-grace 401 case."""
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)
            refresh(response=Response(), refresh_token=token, db=db)

            with pytest.raises(HTTPException) as exc_info:
                refresh(response=Response(), refresh_token=token, db=db)
            assert exc_info.value.status_code == 409
        finally:
            db.close()

    def test_expired_access_token_lifetime_matches_configured_minutes(self, user_id):
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)
            result = refresh(response=Response(), refresh_token=token, db=db)

            payload = jwt.decode(result.access_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            expected = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
            assert abs((expires_at - expected).total_seconds()) < 5
        finally:
            db.close()


class TestRefreshEndpointClearsCookieOnFailure:
    """Goes through the real HTTP layer (`TestClient`) rather than calling `refresh()` directly, because the bug
    this covers only exists there: mutating the injected `Response` on a path that raises `HTTPException` has no
    effect on what FastAPI actually sends, so a direct-call test asserting on a `Response` object would pass while
    the wire response carried no deletion header at all.
    """

    def _post_refresh(self, cookie_value: str) -> httpx.Response:
        client = TestClient(app)
        return client.post("/auth/refresh", headers={"Cookie": f"{REFRESH_TOKEN_COOKIE_NAME}={cookie_value}"})

    def _assert_deletes_refresh_cookie(self, response: httpx.Response) -> None:
        set_cookie = response.headers.get("set-cookie")
        assert set_cookie is not None, "401 response carried no Set-Cookie header at all"
        assert REFRESH_TOKEN_COOKIE_NAME in set_cookie
        assert "Max-Age=0" in set_cookie
        assert f"Path={REFRESH_TOKEN_COOKIE_PATH}" in set_cookie

    def test_unknown_cookie_401_deletes_the_cookie(self):
        response = self._post_refresh("not-a-real-token")

        assert response.status_code == 401
        self._assert_deletes_refresh_cookie(response)

    def test_replayed_rotated_cookie_401_deletes_the_cookie(self, user_id):
        """Replayed from outside the grace window, so this is reuse detection rather than a tab losing a race."""
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)
        finally:
            db.close()

        assert self._post_refresh(token).status_code == 200
        _age_revocations_beyond_grace(user_id)
        response = self._post_refresh(token)

        assert response.status_code == 401
        self._assert_deletes_refresh_cookie(response)

    def test_replay_inside_the_grace_window_returns_409_without_deleting_the_cookie(self, user_id):
        """Two tabs sharing one cookie refresh at once; the loser presents a token rotated away milliseconds ago.
        Deleting the cookie on that response would wipe the winning tab's freshly-set cookie out of the shared jar
        and log the whole browser out -- the spurious multi-device logout the grace window exists to prevent. 409
        (not 401) signals the frontend to retry rather than treat this as a genuinely dead token."""
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)
        finally:
            db.close()

        assert self._post_refresh(token).status_code == 200
        response = self._post_refresh(token)

        assert response.status_code == 409
        assert response.headers.get("set-cookie") is None


class TestRefreshTokenReuseDetection:
    """Replaying a token that was rotated away is the one signal available that a refresh token leaked: the
    legitimate holder and the attacker now both hold something from the same chain, and nothing distinguishes
    them. The response is to revoke the entire family -- deliberately logging the real user out too.
    """

    def test_replay_outside_grace_revokes_every_session_in_the_family(self, user_id):
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id = first_session.family_id
            live_session_id = crud.rotate_session(db, refresh_token=stale_token).session.id
        finally:
            db.close()

        _age_revocations_beyond_grace(user_id)

        db = SessionLocal()
        try:
            result = crud.rotate_session(db, refresh_token=stale_token)
            assert result.outcome is crud.RotationOutcome.REJECTED
        finally:
            db.close()

        # Including the honest session the real user is still holding -- that is what reuse detection means.
        assert _reload_session(live_session_id).revoked_at is not None
        assert _live_sessions_in_family(family_id) == 0

    def test_replay_outside_grace_logs_a_security_warning_without_token_material(self, user_id, caplog):
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id = first_session.family_id
            token_hash = first_session.refresh_token_hash
            crud.rotate_session(db, refresh_token=stale_token)
        finally:
            db.close()

        _age_revocations_beyond_grace(user_id)

        db = SessionLocal()
        try:
            with caplog.at_level(logging.WARNING, logger="app.auth.crud"):
                crud.rotate_session(db, refresh_token=stale_token)
        finally:
            db.close()

        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "Refresh token reuse detected" in message
        assert f"user_id={user_id}" in message
        assert f"family_id={family_id}" in message
        assert "sessions_revoked=1" in message
        assert stale_token not in message
        assert token_hash not in message

    def test_replay_against_an_already_revoked_family_still_logs_a_warning(self, user_id, caplog):
        """Closes a blind spot: a replay of a token whose row was superseded by a normal rotation is genuine reuse
        evidence regardless of whether the rest of the family has since been killed by something else (here,
        logout-all) -- it must not go unlogged just because there is nothing left for `_revoke_family` to claim."""
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id = first_session.family_id
            crud.rotate_session(db, refresh_token=stale_token)
            crud.revoke_all_sessions(db, user_id=user_id)
        finally:
            db.close()

        _age_revocations_beyond_grace(user_id)

        db = SessionLocal()
        try:
            with caplog.at_level(logging.WARNING, logger="app.auth.crud"):
                result = crud.rotate_session(db, refresh_token=stale_token)
                assert result.outcome is crud.RotationOutcome.REJECTED
        finally:
            db.close()

        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "Refresh token reuse detected" in message
        assert f"family_id={family_id}" in message
        assert "sessions_revoked=0" in message

    def test_replay_inside_grace_logs_the_measured_delta(self, user_id, caplog):
        db = SessionLocal()
        try:
            _, stale_token = crud.create_session(db, user_id=user_id)
            crud.rotate_session(db, refresh_token=stale_token)
        finally:
            db.close()

        db = SessionLocal()
        try:
            with caplog.at_level(logging.INFO, logger="app.auth.crud"):
                result = crud.rotate_session(db, refresh_token=stale_token)
                assert result.outcome is crud.RotationOutcome.CONCURRENT_ROTATION
        finally:
            db.close()

        assert "delta_seconds=" in caplog.records[-1].getMessage()

    def test_revoking_a_family_does_not_touch_another_user_s_session_sharing_that_family_id(
        self, user_id, other_user_id
    ):
        """`family_id` is unique per family by construction, so `test_reuse_detection_only_touches_the_offending_
        users_family` above can't exercise the `user_id` filter on `_revoke_family`'s UPDATE -- it passes with or
        without that filter, since the two users' families never collide. Forcing a collision here is what actually
        pins it: this test fails if the `user_id` filter is dropped, where the other one would not."""
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id = first_session.family_id
            crud.rotate_session(db, refresh_token=stale_token)

            other_session, _ = crud.create_session(db, user_id=other_user_id)
            other_session_id = other_session.id
            db.query(UserSession).filter(UserSession.id == other_session_id).update({"family_id": family_id})
            db.commit()
        finally:
            db.close()

        _age_revocations_beyond_grace(user_id)

        db = SessionLocal()
        try:
            crud.rotate_session(db, refresh_token=stale_token)
        finally:
            db.close()

        assert _reload_session(other_session_id).revoked_at is None

    def test_replay_inside_grace_leaves_the_family_alone(self, user_id):
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id = first_session.family_id
            live_session_id = crud.rotate_session(db, refresh_token=stale_token).session.id

            result = crud.rotate_session(db, refresh_token=stale_token)

            assert result.outcome is crud.RotationOutcome.CONCURRENT_ROTATION
        finally:
            db.close()

        assert _reload_session(live_session_id).revoked_at is None
        assert _live_sessions_in_family(family_id) == 1

    def test_an_expired_token_cannot_revoke_the_family(self, user_id):
        """A rotated row outlives its own token: it stays readable for the whole retention window, but the token
        it names stops authenticating at `expires_at`. If reuse were checked before expiry, that dead token would
        keep the power to log the user out of a live session it could no longer access -- so expiry wins.
        """
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id, first_session_id = first_session.family_id, first_session.id
            live_session_id = crud.rotate_session(db, refresh_token=stale_token).session.id
        finally:
            db.close()

        _age_revocations_beyond_grace(user_id)
        _expire_session(first_session_id)

        db = SessionLocal()
        try:
            result = crud.rotate_session(db, refresh_token=stale_token)
            assert result.outcome is crud.RotationOutcome.REJECTED
        finally:
            db.close()

        assert _reload_session(live_session_id).revoked_at is None
        assert _live_sessions_in_family(family_id) == 1

    def test_reuse_detection_only_touches_the_offending_users_family(self, user_id, other_user_id):
        db = SessionLocal()
        try:
            _, stale_token = crud.create_session(db, user_id=user_id)
            crud.rotate_session(db, refresh_token=stale_token)
            other_session, _ = crud.create_session(db, user_id=other_user_id)
            other_session_id = other_session.id
        finally:
            db.close()

        _age_revocations_beyond_grace(user_id)

        db = SessionLocal()
        try:
            crud.rotate_session(db, refresh_token=stale_token)
        finally:
            db.close()

        assert _reload_session(other_session_id).revoked_at is None

    @pytest.mark.parametrize(
        "age_seconds, expected_outcome",
        [
            (REFRESH_REUSE_GRACE_SECONDS - 1, crud.RotationOutcome.CONCURRENT_ROTATION),
            (REFRESH_REUSE_GRACE_SECONDS + 1, crud.RotationOutcome.REJECTED),
        ],
        ids=["just_inside_grace", "just_outside_grace"],
    )
    def test_grace_window_boundary(self, user_id, age_seconds, expected_outcome):
        """The boundary is `now - revoked_at < REFRESH_REUSE_GRACE_SECONDS`, so a replay one second short of the
        window is benign and one second past it is reuse. Pinned here because moving that edge silently is the
        difference between tolerating a two-tab race and revoking a real user's devices.
        """
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id, first_session_id = first_session.family_id, first_session.id
            crud.rotate_session(db, refresh_token=stale_token)
        finally:
            db.close()

        _set_revoked_at(first_session_id, datetime.now(timezone.utc) - timedelta(seconds=age_seconds))

        db = SessionLocal()
        try:
            result = crud.rotate_session(db, refresh_token=stale_token)
            assert result.outcome is expected_outcome
        finally:
            db.close()

        expected_live = 1 if expected_outcome is crud.RotationOutcome.CONCURRENT_ROTATION else 0
        assert _live_sessions_in_family(family_id) == expected_live


class TestLogoutEndpoint:
    def test_revokes_the_matching_session(self, user_id):
        db = SessionLocal()
        try:
            session, token = crud.create_session(db, user_id=user_id)
            session_id = session.id
            logout(response=Response(), refresh_token=token, db=db)
        finally:
            db.close()

        assert _reload_session(session_id).revoked_at is not None

    def test_missing_cookie_does_not_error(self, user_id):
        db = SessionLocal()
        try:
            result = logout(response=Response(), refresh_token=None, db=db)
            assert result.message
        finally:
            db.close()

    def test_logging_out_twice_is_idempotent(self, user_id):
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)
            logout(response=Response(), refresh_token=token, db=db)
            result = logout(response=Response(), refresh_token=token, db=db)
            assert result.message
        finally:
            db.close()

    def test_revoked_session_can_no_longer_be_used_to_refresh(self, user_id):
        """Aged past the grace window so this is unambiguously the dead-token path, not the immediately-after
        benign-replay window every revocation passes through first."""
        db = SessionLocal()
        try:
            _, token = crud.create_session(db, user_id=user_id)
            logout(response=Response(), refresh_token=token, db=db)
        finally:
            db.close()

        _age_revocations_beyond_grace(user_id)

        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                refresh(response=Response(), refresh_token=token, db=db)
            assert exc_info.value.status_code == 401
        finally:
            db.close()

    def test_logout_with_a_token_rotated_away_moments_earlier_still_revokes_the_live_successor(self, user_id):
        """A refresh can complete server-side and rotate the presented token away just before a logout request --
        sent with that same, now-stale, cookie because the browser hadn't seen the refresh response yet -- reaches
        the server. Logout must still kill the rotated successor rather than finding its own (already-revoked)
        row a no-op and leaving the live successor behind."""
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id = first_session.family_id
            live_session_id = crud.rotate_session(db, refresh_token=stale_token).session.id

            logout(response=Response(), refresh_token=stale_token, db=db)
        finally:
            db.close()

        assert _reload_session(live_session_id).revoked_at is not None
        assert _live_sessions_in_family(family_id) == 0

    def test_expired_token_cannot_be_used_to_log_out_a_live_family(self, user_id):
        """Mirrors `test_an_expired_token_cannot_revoke_the_family` for the logout path: a long-dead ancestor
        token must not retain the power to kill every device in a family it can no longer even authenticate
        with."""
        db = SessionLocal()
        try:
            first_session, stale_token = crud.create_session(db, user_id=user_id)
            family_id, first_session_id = first_session.family_id, first_session.id
            live_session_id = crud.rotate_session(db, refresh_token=stale_token).session.id
        finally:
            db.close()

        _expire_session(first_session_id)

        db = SessionLocal()
        try:
            logout(response=Response(), refresh_token=stale_token, db=db)
        finally:
            db.close()

        assert _reload_session(live_session_id).revoked_at is None
        assert _live_sessions_in_family(family_id) == 1

    def test_concurrent_refresh_and_logout_do_not_orphan_a_live_successor(self, user_id):
        """Runs several times to vary real thread/connection scheduling: whichever of a `/auth/refresh` and a
        `/auth/logout` racing on the same family reaches the database first, the family must end up with zero live
        sessions either way -- the per-family advisory lock (`crud._lock_family`) is what makes that true
        regardless of interleaving, not just the already-fixed case where one fully finishes before the other
        starts."""
        for _ in range(20):
            db = SessionLocal()
            try:
                first_session, stale_token = crud.create_session(db, user_id=user_id)
                family_id = first_session.family_id
            finally:
                db.close()

            def do_refresh():
                thread_db = SessionLocal()
                try:
                    crud.rotate_session(thread_db, refresh_token=stale_token)
                finally:
                    thread_db.close()

            def do_logout():
                thread_db = SessionLocal()
                try:
                    crud.revoke_session_by_token(thread_db, refresh_token=stale_token)
                finally:
                    thread_db.close()

            t1 = threading.Thread(target=do_refresh)
            t2 = threading.Thread(target=do_logout)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            assert _live_sessions_in_family(family_id) == 0


class TestLogoutAllEndpoint:
    def test_revokes_every_live_session_for_the_user(self, user_id):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            _, token_a = crud.create_session(db, user_id=user_id)
            _, token_b = crud.create_session(db, user_id=user_id)

            logout_all(response=Response(), current_user=user, db=db)

            assert crud.rotate_session(db, refresh_token=token_a).outcome is not crud.RotationOutcome.ROTATED
            assert crud.rotate_session(db, refresh_token=token_b).outcome is not crud.RotationOutcome.ROTATED
        finally:
            db.close()

    def test_does_not_touch_another_user_s_sessions(self, user_id, other_user_id):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            _, own_token = crud.create_session(db, user_id=user_id)
            _, other_token = crud.create_session(db, user_id=other_user_id)

            logout_all(response=Response(), current_user=user, db=db)

            assert crud.rotate_session(db, refresh_token=own_token).outcome is not crud.RotationOutcome.ROTATED
            assert crud.rotate_session(db, refresh_token=other_token).outcome is crud.RotationOutcome.ROTATED
        finally:
            db.close()
