"""Tests for POST /auth/reset-password (app/auth/routers.py::reset_password):
a valid, unused, unexpired token updates the password and marks the token
(and every other outstanding token for that user) used; expired/tampered/
already-used/nonexistent tokens all fail the same way (400, generic detail)
and leave the password unchanged -- same discipline as
test_verify_email_endpoint.py, but reset-password additionally must
invalidate sibling tokens on success (see the docstring on reset_password)
and validate new_password through the same length constraints as signup.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import threading

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.auth.models import PasswordResetToken, User
from app.auth.routers import reset_password
from app.auth.schemas import ResetPasswordRequest
from app.auth.security import create_password_reset_token, verify_password
from app.db.session import SessionLocal

TEST_EMAIL = "reset-password-test@example.com"
OLD_PASSWORD_HASH = "not-a-real-hash"
NEW_PASSWORD = "a-brand-new-correct-horse"


@pytest.fixture
def user_with_password():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is not None:
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()

        user = User(email=TEST_EMAIL, hashed_password=OLD_PASSWORD_HASH, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    finally:
        db.close()


def _reload_user(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


class TestResetPasswordValidToken:
    def test_valid_token_updates_the_password(self, user_with_password):
        db = SessionLocal()
        try:
            token = create_password_reset_token(db, user_with_password)

            response = reset_password(ResetPasswordRequest(token=token, new_password=NEW_PASSWORD), db=db)

            assert response.message
            updated = _reload_user(user_with_password)
            assert updated.hashed_password != OLD_PASSWORD_HASH
            assert verify_password(NEW_PASSWORD, updated.hashed_password)
        finally:
            db.close()

    def test_valid_token_marks_the_row_used(self, user_with_password):
        db = SessionLocal()
        try:
            token = create_password_reset_token(db, user_with_password)
            token_id = db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user_with_password
            ).first().id

            reset_password(ResetPasswordRequest(token=token, new_password=NEW_PASSWORD), db=db)

            token_row = db.query(PasswordResetToken).filter(PasswordResetToken.id == token_id).first()
            assert token_row.used_at is not None
        finally:
            db.close()

    def test_success_invalidates_other_outstanding_tokens_for_the_same_user(self, user_with_password):
        db = SessionLocal()
        try:
            create_password_reset_token(db, user_with_password)
            stale_token_id = (
                db.query(PasswordResetToken)
                .filter(PasswordResetToken.user_id == user_with_password)
                .order_by(PasswordResetToken.created_at.asc())
                .first()
                .id
            )
            fresh_token = create_password_reset_token(db, user_with_password)

            reset_password(ResetPasswordRequest(token=fresh_token, new_password=NEW_PASSWORD), db=db)

            stale_row = db.query(PasswordResetToken).filter(PasswordResetToken.id == stale_token_id).first()
            assert stale_row.used_at is not None
        finally:
            db.close()

    def test_invalidated_sibling_token_can_no_longer_be_used(self, user_with_password):
        from app.auth.security import PasswordResetTokenError, verify_password_reset_token

        db = SessionLocal()
        try:
            stale_token = create_password_reset_token(db, user_with_password)
            fresh_token = create_password_reset_token(db, user_with_password)

            reset_password(ResetPasswordRequest(token=fresh_token, new_password=NEW_PASSWORD), db=db)

            with pytest.raises(PasswordResetTokenError) as exc_info:
                verify_password_reset_token(db, stale_token)
            assert exc_info.value.reason == "already_used"
        finally:
            db.close()


class TestResetPasswordInvalidToken:
    def test_tampered_token_returns_400_and_leaves_password_unchanged(self, user_with_password):
        db = SessionLocal()
        try:
            token = create_password_reset_token(db, user_with_password)
            tampered = ("a" if token[0] != "a" else "b") + token[1:]

            with pytest.raises(HTTPException) as exc_info:
                reset_password(ResetPasswordRequest(token=tampered, new_password=NEW_PASSWORD), db=db)

            assert exc_info.value.status_code == 400
            assert "invalid" in exc_info.value.detail.lower()
            assert _reload_user(user_with_password).hashed_password == OLD_PASSWORD_HASH
        finally:
            db.close()

    def test_expired_token_returns_400_and_leaves_password_unchanged(self, user_with_password, monkeypatch):
        db = SessionLocal()
        try:
            token = create_password_reset_token(db, user_with_password)
            monkeypatch.setattr("app.auth.security.PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS", -1)

            with pytest.raises(HTTPException) as exc_info:
                reset_password(ResetPasswordRequest(token=token, new_password=NEW_PASSWORD), db=db)

            assert exc_info.value.status_code == 400
            assert _reload_user(user_with_password).hashed_password == OLD_PASSWORD_HASH
        finally:
            db.close()

    def test_already_used_token_returns_400_and_does_not_reprocess(self, user_with_password):
        db = SessionLocal()
        try:
            token = create_password_reset_token(db, user_with_password)
            reset_password(ResetPasswordRequest(token=token, new_password=NEW_PASSWORD), db=db)
            first_reset_hash = _reload_user(user_with_password).hashed_password

            with pytest.raises(HTTPException) as exc_info:
                reset_password(ResetPasswordRequest(token=token, new_password="a-different-password-entirely"), db=db)

            assert exc_info.value.status_code == 400
            assert _reload_user(user_with_password).hashed_password == first_reset_hash
        finally:
            db.close()

    def test_nonexistent_token_returns_400_and_leaves_password_unchanged(self, user_with_password):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                reset_password(ResetPasswordRequest(token="not-a-real-token", new_password=NEW_PASSWORD), db=db)

            assert exc_info.value.status_code == 400
            assert _reload_user(user_with_password).hashed_password == OLD_PASSWORD_HASH
        finally:
            db.close()


class TestResetPasswordConcurrency:
    def test_concurrent_requests_with_the_same_token_only_one_succeeds(self, user_with_password):
        """Two near-simultaneous reset-password requests replaying the same
        valid token, each on its own DB session/connection (mirrors two real
        concurrent HTTP requests). The used_at check-and-set must be atomic:
        exactly one should succeed and the other must fail as already_used,
        never both.
        """
        db = SessionLocal()
        try:
            token = create_password_reset_token(db, user_with_password)
        finally:
            db.close()

        results = {}

        def attempt(name, password):
            thread_db = SessionLocal()
            try:
                try:
                    reset_password(ResetPasswordRequest(token=token, new_password=password), db=thread_db)
                    results[name] = "success"
                except HTTPException as exc:
                    results[name] = exc.status_code
            finally:
                thread_db.close()

        t1 = threading.Thread(target=attempt, args=("a", "password-from-request-a"))
        t2 = threading.Thread(target=attempt, args=("b", "password-from-request-b"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [v for v in results.values() if v == "success"]
        failures = [v for v in results.values() if v == 400]
        assert len(successes) == 1, f"expected exactly one success, got {results}"
        assert len(failures) == 1, f"expected exactly one already_used failure, got {results}"


class TestResetPasswordNewPasswordLengthValidation:
    def test_too_short_new_password_rejected(self):
        with pytest.raises(ValidationError):
            ResetPasswordRequest(token="irrelevant", new_password="a" * (PASSWORD_MIN_LENGTH - 1))

    def test_too_long_new_password_rejected(self):
        with pytest.raises(ValidationError):
            ResetPasswordRequest(token="irrelevant", new_password="a" * (PASSWORD_MAX_LENGTH + 1))

    def test_valid_length_new_password_accepted(self):
        instance = ResetPasswordRequest(token="irrelevant", new_password="a" * PASSWORD_MIN_LENGTH)
        assert instance.new_password == "a" * PASSWORD_MIN_LENGTH
