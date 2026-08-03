"""Tests for POST /auth/signup (app/auth/routers.py::signup): a successful
signup issues an EmailVerificationToken row and queues the verification
email via FastAPI's BackgroundTasks (not sent inline, so signup itself isn't
blocked on SMTP), and the new user starts inactive as before.

Router functions are called directly with a real DB session and a real
BackgroundTasks instance, following the existing pattern in
test_self_capture_writes_event.py -- no TestClient/HTTP layer in this repo's
test suite. EmailProvider.send is mocked (app.auth.routers.get_email_provider
is patched to return a fake) since no real SMTP send should happen in tests;
this mirrors how test_email_provider.py isolates aiosmtplib.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import asyncio

import pytest
from fastapi import BackgroundTasks

from app.auth.models import EmailVerificationToken, User
from app.auth.routers import signup
from app.auth.schemas import UserSignup
from app.db.session import SessionLocal

TEST_EMAIL = "signup-verification-email-test@example.com"


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
def clean_test_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is not None:
            db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is not None:
            db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()
    finally:
        db.close()


class TestSignupQueuesVerificationEmail:
    def test_signup_creates_inactive_user(self, clean_test_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = UserSignup(email=TEST_EMAIL, password="correct-horse-battery", name="Test User")
            background_tasks = BackgroundTasks()

            signup(payload, background_tasks, db=db)

            user = db.query(User).filter(User.email == TEST_EMAIL).first()
            assert user.is_active is False
        finally:
            db.close()

    def test_signup_creates_a_verification_token_row(self, clean_test_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = UserSignup(email=TEST_EMAIL, password="correct-horse-battery", name="Test User")
            background_tasks = BackgroundTasks()

            signup(payload, background_tasks, db=db)

            user = db.query(User).filter(User.email == TEST_EMAIL).first()
            token_row = (
                db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user.id).first()
            )
            assert token_row is not None
            assert token_row.used_at is None
        finally:
            db.close()

    def test_signup_queues_but_does_not_block_on_the_email_send(self, clean_test_user, fake_email_provider):
        db = SessionLocal()
        try:
            payload = UserSignup(email=TEST_EMAIL, password="correct-horse-battery", name="Test User")
            background_tasks = BackgroundTasks()

            signup(payload, background_tasks, db=db)

            # Not sent yet -- signup returned before the background task ran.
            assert fake_email_provider.calls == []
            assert len(background_tasks.tasks) == 1

            asyncio.run(background_tasks())

            assert len(fake_email_provider.calls) == 1
            assert fake_email_provider.calls[0]["to"] == TEST_EMAIL
            assert "verify" in fake_email_provider.calls[0]["subject"].lower()
        finally:
            db.close()

    def test_duplicate_signup_returns_the_same_generic_message_and_does_not_queue_a_second_email(
        self, clean_test_user, fake_email_provider
    ):
        db = SessionLocal()
        try:
            payload = UserSignup(email=TEST_EMAIL, password="correct-horse-battery", name="Test User")
            original = signup(payload, BackgroundTasks(), db=db)

            duplicate_background_tasks = BackgroundTasks()
            duplicate = signup(payload, duplicate_background_tasks, db=db)

            assert duplicate.message == original.message
            assert duplicate_background_tasks.tasks == []

            users = db.query(User).filter(User.email == TEST_EMAIL).all()
            assert len(users) == 1
        finally:
            db.close()
