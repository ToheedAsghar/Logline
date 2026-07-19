"""Tests for POST /auth/resend-verification (app/auth/routers.py::
resend_verification): a repeat request within
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS of the last token silently skips
sending and returns the same generic 200 as every other case (nonexistent
email, already verified, real send) -- a distinct status code (e.g. 429)
would itself leak that the account exists and is eligible, defeating the
anti-enumeration design. A request after the cooldown has passed queues a
fresh token/email as normal.

The cooldown constant is monkeypatched to a very short/zero value rather
than sleeping in the "cooldown passed" case, per the same style as
test_email_verification_token.py's expired-token test.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import asyncio

import pytest
from fastapi import BackgroundTasks

from app.auth.models import EmailVerificationToken, User
from app.auth.routers import resend_verification
from app.auth.schemas import ResendVerificationRequest
from app.db.session import SessionLocal

TEST_EMAIL = "resend-verification-cooldown-test@example.com"
NONEXISTENT_EMAIL = "resend-verification-nonexistent@example.com"


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


class TestResendVerificationCooldown:
    def test_first_request_sends_and_queues_a_token(self, inactive_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = ResendVerificationRequest(email=TEST_EMAIL)
            background_tasks = BackgroundTasks()

            resend_verification(payload, background_tasks, db=db)

            assert len(background_tasks.tasks) == 1
            token_row = (
                db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == inactive_user).first()
            )
            assert token_row is not None
        finally:
            db.close()

    def test_second_request_within_cooldown_returns_generic_200_without_sending(
        self, inactive_user, fake_email_provider
    ):
        db = SessionLocal()
        try:
            payload = ResendVerificationRequest(email=TEST_EMAIL)
            first_response = resend_verification(payload, BackgroundTasks(), db=db)

            second_background_tasks = BackgroundTasks()
            second_response = resend_verification(payload, second_background_tasks, db=db)

            assert second_response.message == first_response.message
            assert second_background_tasks.tasks == []
            token_rows = (
                db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == inactive_user).all()
            )
            assert len(token_rows) == 1
        finally:
            db.close()

    def test_request_after_cooldown_expires_succeeds(self, inactive_user, fake_email_provider, monkeypatch):
        db = SessionLocal()
        try:
            payload = ResendVerificationRequest(email=TEST_EMAIL)
            resend_verification(payload, BackgroundTasks(), db=db)

            monkeypatch.setattr("app.auth.routers.EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS", 0)

            second_background_tasks = BackgroundTasks()
            resend_verification(payload, second_background_tasks, db=db)

            assert len(second_background_tasks.tasks) == 1
            token_rows = (
                db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == inactive_user).all()
            )
            assert len(token_rows) == 2
        finally:
            db.close()

    def test_cooldown_respected_email_actually_sent_once_allowed(
        self, inactive_user, fake_email_provider, monkeypatch
    ):
        db = SessionLocal()
        try:
            payload = ResendVerificationRequest(email=TEST_EMAIL)
            background_tasks = BackgroundTasks()
            resend_verification(payload, background_tasks, db=db)
            asyncio.run(background_tasks())

            assert len(fake_email_provider.calls) == 1
        finally:
            db.close()


class TestResendVerificationDoesNotLeakAccountState:
    def test_nonexistent_email_returns_generic_200_without_sending(self, fake_email_provider):
        db = SessionLocal()
        try:
            payload = ResendVerificationRequest(email=NONEXISTENT_EMAIL)
            background_tasks = BackgroundTasks()

            response = resend_verification(payload, background_tasks, db=db)

            assert response.message
            assert background_tasks.tasks == []
        finally:
            db.close()

    def test_already_active_user_returns_generic_200_without_sending(self, fake_email_provider):
        db = SessionLocal()
        try:
            email = "resend-verification-already-active@example.com"
            db.query(User).filter(User.email == email).delete()
            db.commit()
            user = User(email=email, hashed_password="not-a-real-hash", is_active=True)
            db.add(user)
            db.commit()

            try:
                payload = ResendVerificationRequest(email=email)
                background_tasks = BackgroundTasks()

                response = resend_verification(payload, background_tasks, db=db)

                assert response.message
                assert background_tasks.tasks == []
            finally:
                db.query(User).filter(User.email == email).delete()
                db.commit()
        finally:
            db.close()

    def test_cooldown_response_is_identical_to_nonexistent_email_response(self, inactive_user, fake_email_provider):
        """The whole point of the fix: a caller comparing two rapid requests
        -- one for a real, eligible email under cooldown, one for an email
        that was never registered -- must see no difference in status code
        or body, since a distinct response would itself be the enumeration
        leak.
        """
        db = SessionLocal()
        try:
            real_payload = ResendVerificationRequest(email=TEST_EMAIL)
            resend_verification(real_payload, BackgroundTasks(), db=db)
            cooldown_response = resend_verification(real_payload, BackgroundTasks(), db=db)

            nonexistent_response = resend_verification(
                ResendVerificationRequest(email=NONEXISTENT_EMAIL), BackgroundTasks(), db=db
            )

            assert cooldown_response.model_dump() == nonexistent_response.model_dump()
        finally:
            db.close()
