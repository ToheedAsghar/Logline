"""Tests for POST /auth/forgot-password (app/auth/routers.py::forgot_password):
identical generic responses for a real match, a nonexistent email, an
SSO-only account, and a real match under cooldown -- same email-enumeration
discipline as test_resend_verification_cooldown.py's resend-verification
tests. A repeat request within PASSWORD_RESET_RESEND_COOLDOWN_SECONDS
silently skips sending and returns the same generic 200 as every other
case; a distinct status code (e.g. 429) would itself leak that the account
exists and is eligible, so cooldown enforcement must be invisible in the
response. Cooldown mechanics mirror the verification-resend cooldown, just
against PasswordResetToken instead of EmailVerificationToken.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import asyncio

import pytest
from fastapi import BackgroundTasks

from app.auth.models import PasswordResetToken, User
from app.auth.routers import forgot_password
from app.auth.schemas import ForgotPasswordRequest
from app.db.session import SessionLocal

TEST_EMAIL = "forgot-password-test@example.com"
SSO_EMAIL = "forgot-password-sso-test@example.com"
NONEXISTENT_EMAIL = "forgot-password-nonexistent@example.com"


class FakeEmailProvider:
    def __init__(self):
        self.calls = []

    async def send(self, to, subject, body):
        self.calls.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def fake_email_provider(monkeypatch):
    provider = FakeEmailProvider()
    monkeypatch.setattr("app.auth.routers.get_email_provider", lambda: provider)
    return provider


@pytest.fixture
def real_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is not None:
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()

        user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash", is_active=True, is_sso_user=False)
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


@pytest.fixture
def sso_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == SSO_EMAIL).first()
        if user is not None:
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()

        user = User(email=SSO_EMAIL, hashed_password="not-a-real-hash", is_active=True, is_sso_user=True)
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


class TestForgotPasswordRealAccount:
    def test_real_account_gets_generic_response_and_queues_token(self, real_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = ForgotPasswordRequest(email=TEST_EMAIL)
            background_tasks = BackgroundTasks()

            response = forgot_password(payload, background_tasks, db=db)

            assert response.message
            assert len(background_tasks.tasks) == 1
            token_row = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == real_user).first()
            assert token_row is not None
        finally:
            db.close()

    def test_real_account_email_actually_sent(self, real_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = ForgotPasswordRequest(email=TEST_EMAIL)
            background_tasks = BackgroundTasks()
            forgot_password(payload, background_tasks, db=db)
            asyncio.run(background_tasks())

            assert len(fake_email_provider.calls) == 1
            assert fake_email_provider.calls[0]["to"] == TEST_EMAIL
        finally:
            db.close()

    def test_second_request_within_cooldown_returns_generic_response_without_sending(
        self, real_user, fake_email_provider
    ):
        db = SessionLocal()
        try:
            payload = ForgotPasswordRequest(email=TEST_EMAIL)
            first_response = forgot_password(payload, BackgroundTasks(), db=db)

            second_background_tasks = BackgroundTasks()
            second_response = forgot_password(payload, second_background_tasks, db=db)

            assert second_response.message == first_response.message
            assert second_background_tasks.tasks == []
            token_rows = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == real_user).all()
            assert len(token_rows) == 1
        finally:
            db.close()

    def test_request_after_cooldown_expires_succeeds(self, real_user, fake_email_provider, monkeypatch):
        db = SessionLocal()
        try:
            payload = ForgotPasswordRequest(email=TEST_EMAIL)
            forgot_password(payload, BackgroundTasks(), db=db)

            monkeypatch.setattr("app.auth.routers.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", 0)

            second_background_tasks = BackgroundTasks()
            forgot_password(payload, second_background_tasks, db=db)

            assert len(second_background_tasks.tasks) == 1
            token_rows = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == real_user).all()
            assert len(token_rows) == 2
        finally:
            db.close()


class TestForgotPasswordDoesNotLeakAccountState:
    def test_nonexistent_email_returns_generic_response_without_sending(self, fake_email_provider):
        db = SessionLocal()
        try:
            payload = ForgotPasswordRequest(email=NONEXISTENT_EMAIL)
            background_tasks = BackgroundTasks()

            response = forgot_password(payload, background_tasks, db=db)

            assert response.message
            assert background_tasks.tasks == []
        finally:
            db.close()

    def test_sso_account_returns_generic_response_without_sending(self, sso_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = ForgotPasswordRequest(email=SSO_EMAIL)
            background_tasks = BackgroundTasks()

            response = forgot_password(payload, background_tasks, db=db)

            assert response.message
            assert background_tasks.tasks == []
            token_row = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == sso_user).first()
            assert token_row is None
        finally:
            db.close()

    def test_response_message_is_identical_across_real_nonexistent_and_sso_cases(
        self, real_user, sso_user, fake_email_provider
    ):
        db = SessionLocal()
        try:
            real_response = forgot_password(ForgotPasswordRequest(email=TEST_EMAIL), BackgroundTasks(), db=db)
            nonexistent_response = forgot_password(
                ForgotPasswordRequest(email=NONEXISTENT_EMAIL), BackgroundTasks(), db=db
            )
            sso_response = forgot_password(ForgotPasswordRequest(email=SSO_EMAIL), BackgroundTasks(), db=db)

            assert real_response.message == nonexistent_response.message == sso_response.message
        finally:
            db.close()

    def test_cooldown_response_is_identical_to_nonexistent_email_response(self, real_user, fake_email_provider):
        """The whole point of the fix: a caller comparing two rapid requests
        -- one for a real, eligible email under cooldown, one for an email
        that was never registered -- must see no difference in status code
        or body, since a distinct response would itself be the enumeration
        leak.
        """
        db = SessionLocal()
        try:
            real_payload = ForgotPasswordRequest(email=TEST_EMAIL)
            forgot_password(real_payload, BackgroundTasks(), db=db)
            cooldown_response = forgot_password(real_payload, BackgroundTasks(), db=db)

            nonexistent_response = forgot_password(
                ForgotPasswordRequest(email=NONEXISTENT_EMAIL), BackgroundTasks(), db=db
            )

            assert cooldown_response.model_dump() == nonexistent_response.model_dump()
        finally:
            db.close()
