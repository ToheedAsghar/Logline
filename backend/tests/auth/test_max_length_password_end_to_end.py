"""End-to-end confirmation that PASSWORD_MAX_LENGTH (128 characters) is
genuinely usable through signup, login, and reset -- not just accepted by
the pydantic schema layer and then silently broken at the bcrypt layer (the
bcrypt-5.x-crashes-on->72-bytes bug fixed in app/auth/security.py). Each
test below drives the real router function with a real DB session, the
same pattern as test_signup_sends_verification_email.py /
test_login_rejects_unverified_user.py / test_reset_password.py.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import pytest
from fastapi import BackgroundTasks, Response

from app.auth.constants import PASSWORD_MAX_LENGTH
from app.auth.models import EmailVerificationToken, PasswordResetToken, User, UserSession
from app.auth.routers import login, reset_password, signup
from app.auth.schemas import ResetPasswordRequest, UserLogin, UserSignup
from app.auth.security import create_password_reset_token, hash_password, verify_password
from app.db.session import SessionLocal

TEST_EMAIL = "max-length-password-e2e-test@example.com"
MAX_LENGTH_PASSWORD = "a" * PASSWORD_MAX_LENGTH


class FakeEmailProvider:
    async def send(self, to, subject, body):
        pass


@pytest.fixture
def fake_email_provider(monkeypatch):
    monkeypatch.setattr("app.auth.routers.get_email_provider", lambda: FakeEmailProvider())


@pytest.fixture
def clean_test_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is not None:
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
            db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user.id).delete()
            db.query(UserSession).filter(UserSession.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is not None:
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
            db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user.id).delete()
            db.query(UserSession).filter(UserSession.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()
    finally:
        db.close()


class TestMaximumLengthPasswordEndToEnd:
    def test_signup_succeeds_with_a_maximum_length_password(self, clean_test_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = UserSignup(email=TEST_EMAIL, password=MAX_LENGTH_PASSWORD, name="Test User")

            signup(payload, BackgroundTasks(), db=db)

            user = db.query(User).filter(User.email == TEST_EMAIL).first()
            assert user.email == TEST_EMAIL
            assert verify_password(MAX_LENGTH_PASSWORD, user.hashed_password)
        finally:
            db.close()

    def test_login_succeeds_with_a_maximum_length_password(self, clean_test_user):
        db = SessionLocal()
        try:
            user = User(email=TEST_EMAIL, hashed_password=hash_password(MAX_LENGTH_PASSWORD), is_active=True)
            db.add(user)
            db.commit()

            token = login(UserLogin(email=TEST_EMAIL, password=MAX_LENGTH_PASSWORD), response=Response(), db=db)

            assert token.access_token
        finally:
            db.close()

    def test_reset_password_succeeds_with_a_maximum_length_new_password(self, clean_test_user):
        db = SessionLocal()
        try:
            user = User(email=TEST_EMAIL, hashed_password=hash_password("original-password"), is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)
            token = create_password_reset_token(db, user.id)

            reset_password(ResetPasswordRequest(token=token, new_password=MAX_LENGTH_PASSWORD), db=db)

            updated = db.query(User).filter(User.id == user.id).first()
            assert verify_password(MAX_LENGTH_PASSWORD, updated.hashed_password)
        finally:
            db.close()
