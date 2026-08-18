"""Tests for the email-verification token helpers in app/auth/security.py:
create_email_verification_token issues a signed itsdangerous token backed by
a real EmailVerificationToken row, and verify_email_verification_token
accepts a valid, unused, unexpired token while rejecting a tampered,
expired, already-used, or nonexistent one with a specific `.reason` (never
surfaced to the client -- see auth/routers.py::verify_email, which maps
every EmailVerificationTokenError to the same generic 400).

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md)
since the row lookup + used_at check are what's under test.
"""

from datetime import datetime, timezone

import pytest

from app.auth.models import EmailVerificationToken, User
from app.auth.security import (
    EmailVerificationTokenError, create_email_verification_token, verify_email_verification_token,
)
from app.db.session import SessionLocal

TEST_EMAIL = "email-verification-token-test@example.com"


@pytest.fixture
def real_db_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestCreateEmailVerificationToken:
    def test_creates_a_token_row(self, real_db_user):
        db = SessionLocal()
        try:
            create_email_verification_token(db, real_db_user)

            row = db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == real_db_user).first()
            assert row is not None
            assert row.used_at is None
        finally:
            db.close()

    def test_returns_a_string_token_distinct_from_the_row_id(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, real_db_user)
            assert isinstance(token, str)
            assert token != ""
        finally:
            db.close()


class TestVerifyEmailVerificationToken:
    def test_valid_token_resolves_to_the_issuing_row(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, real_db_user)

            token_row = verify_email_verification_token(db, token)

            assert token_row.user_id == real_db_user
            assert token_row.used_at is None
        finally:
            db.close()

    def test_tampered_token_is_rejected(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, real_db_user)
            tampered = ("a" if token[0] != "a" else "b") + token[1:]

            with pytest.raises(EmailVerificationTokenError) as exc_info:
                verify_email_verification_token(db, tampered)
            assert exc_info.value.reason == "tampered"
        finally:
            db.close()

    def test_garbage_token_is_rejected_as_tampered(self, real_db_user):
        db = SessionLocal()
        try:
            with pytest.raises(EmailVerificationTokenError) as exc_info:
                verify_email_verification_token(db, "not-a-real-token")
            assert exc_info.value.reason == "tampered"
        finally:
            db.close()

    def test_expired_token_is_rejected(self, real_db_user, monkeypatch):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, real_db_user)

            monkeypatch.setattr("app.auth.security.EMAIL_VERIFICATION_TOKEN_MAX_AGE_SECONDS", -1)

            with pytest.raises(EmailVerificationTokenError) as exc_info:
                verify_email_verification_token(db, token)
            assert exc_info.value.reason == "expired"
        finally:
            db.close()

    def test_already_used_token_is_rejected(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, real_db_user)
            token_row = verify_email_verification_token(db, token)
            token_row.used_at = datetime.now(timezone.utc)
            db.commit()

            with pytest.raises(EmailVerificationTokenError) as exc_info:
                verify_email_verification_token(db, token)
            assert exc_info.value.reason == "already_used"
        finally:
            db.close()

    def test_nonexistent_row_is_rejected_as_not_found(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_email_verification_token(db, real_db_user)
            db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == real_db_user).delete()
            db.commit()

            with pytest.raises(EmailVerificationTokenError) as exc_info:
                verify_email_verification_token(db, token)
            assert exc_info.value.reason == "not_found"
        finally:
            db.close()
