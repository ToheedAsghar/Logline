"""Tests for GET /auth/verify-email (app/auth/routers.py::verify_email): a
valid, unused, unexpired token activates the user and marks the token row
used; an expired/tampered/already-used/nonexistent token all fail the same
way (400, generic detail) and leave the user inactive -- the specific
failure reason is only ever logged server-side, never returned to the
caller (see EmailVerificationTokenError in app/auth/security.py).

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import pytest
from fastapi import HTTPException

from app.auth.models import EmailVerificationToken, User
from app.auth.routers import verify_email
from app.auth.security import create_email_verification_token
from app.db.session import SessionLocal

TEST_EMAIL = "verify-email-endpoint-test@example.com"


@pytest.fixture
def inactive_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is not None:
            db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()

        user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash", is_active=False)
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user_id).delete()
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


class TestVerifyEmailValidToken:
    def test_valid_token_activates_the_user(self, inactive_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, inactive_user)

            response = verify_email(token, db=db)

            assert response.message == "Email verified successfully"
            assert _reload_user(inactive_user).is_active is True
        finally:
            db.close()

    def test_valid_token_marks_the_row_used(self, inactive_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, inactive_user)

            verify_email(token, db=db)

            token_row = (
                db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == inactive_user).first()
            )
            assert token_row.used_at is not None
        finally:
            db.close()


class TestVerifyEmailInvalidToken:
    def test_tampered_token_returns_400_and_leaves_user_inactive(self, inactive_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, inactive_user)
            tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

            with pytest.raises(HTTPException) as exc_info:
                verify_email(tampered, db=db)

            assert exc_info.value.status_code == 400
            assert "invalid" in exc_info.value.detail.lower()
            assert _reload_user(inactive_user).is_active is False
        finally:
            db.close()

    def test_expired_token_returns_400_and_leaves_user_inactive(self, inactive_user, monkeypatch):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, inactive_user)
            # -1 forces immediate expiry -- see test_email_verification_token.py.
            monkeypatch.setattr("app.auth.security.EMAIL_VERIFICATION_TOKEN_MAX_AGE_SECONDS", -1)

            with pytest.raises(HTTPException) as exc_info:
                verify_email(token, db=db)

            assert exc_info.value.status_code == 400
            assert _reload_user(inactive_user).is_active is False
        finally:
            db.close()

    def test_already_used_token_returns_400_and_stays_activated_but_does_not_reprocess(
        self, inactive_user
    ):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, inactive_user)
            verify_email(token, db=db)
            assert _reload_user(inactive_user).is_active is True

            with pytest.raises(HTTPException) as exc_info:
                verify_email(token, db=db)
            assert exc_info.value.status_code == 400
        finally:
            db.close()

    def test_nonexistent_token_returns_400_and_leaves_user_inactive(self, inactive_user):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                verify_email("not-a-real-token", db=db)

            assert exc_info.value.status_code == 400
            assert _reload_user(inactive_user).is_active is False
        finally:
            db.close()
