"""Tests for POST /auth/login (app/auth/routers.py::login): an unverified
(is_active=False) account is rejected with a distinct error from a wrong
password, so the frontend can tell the user to check their email rather
than implying they mistyped their password. The is_active check only runs
after the password has already been verified correct -- checking it first
would let a caller distinguish "wrong password" from "right password, just
unverified" without ever proving they know the password, leaking account
existence to a blind guesser.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import pytest
from fastapi import HTTPException, Response

from app.auth.models import User, UserSession
from app.auth.routers import login
from app.auth.schemas import UserLogin
from app.auth.security import hash_password
from app.db.session import SessionLocal

TEST_EMAIL = "login-unverified-test@example.com"
TEST_PASSWORD = "correct-horse-battery"


def _delete_user_and_sessions(db, email: str) -> None:
    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        db.query(UserSession).filter(UserSession.user_id == existing.id).delete()
        db.query(User).filter(User.id == existing.id).delete()
        db.commit()


@pytest.fixture
def user_factory():
    created_emails = []

    def _create(*, is_active: bool) -> None:
        db = SessionLocal()
        try:
            _delete_user_and_sessions(db, TEST_EMAIL)
            user = User(
                email=TEST_EMAIL,
                hashed_password=hash_password(TEST_PASSWORD),
                is_active=is_active,
            )
            db.add(user)
            db.commit()
            created_emails.append(TEST_EMAIL)
        finally:
            db.close()

    yield _create

    db = SessionLocal()
    try:
        _delete_user_and_sessions(db, TEST_EMAIL)
    finally:
        db.close()


class TestLoginRejectsUnverifiedUser:
    def test_unverified_user_with_correct_password_gets_403_not_401(self, user_factory):
        user_factory(is_active=False)
        db = SessionLocal()
        try:
            payload = UserLogin(email=TEST_EMAIL, password=TEST_PASSWORD)

            with pytest.raises(HTTPException) as exc_info:
                login(payload, response=Response(), db=db)

            assert exc_info.value.status_code == 403
            assert "verif" in exc_info.value.detail.lower()
        finally:
            db.close()

    def test_unverified_user_with_wrong_password_still_gets_401(self, user_factory):
        user_factory(is_active=False)
        db = SessionLocal()
        try:
            payload = UserLogin(email=TEST_EMAIL, password="totally-wrong-password")

            with pytest.raises(HTTPException) as exc_info:
                login(payload, response=Response(), db=db)

            # Wrong password is checked before is_active, so this must stay
            # 401 with the generic message -- not 403, which would leak that
            # the account exists and is merely unverified.
            assert exc_info.value.status_code == 401
            assert "verif" not in exc_info.value.detail.lower()
        finally:
            db.close()

    def test_verified_user_with_correct_password_logs_in(self, user_factory):
        user_factory(is_active=True)
        db = SessionLocal()
        try:
            payload = UserLogin(email=TEST_EMAIL, password=TEST_PASSWORD)

            token = login(payload, response=Response(), db=db)

            assert token.access_token
        finally:
            db.close()

    def test_verified_user_with_wrong_password_gets_401(self, user_factory):
        user_factory(is_active=True)
        db = SessionLocal()
        try:
            payload = UserLogin(email=TEST_EMAIL, password="totally-wrong-password")

            with pytest.raises(HTTPException) as exc_info:
                login(payload, response=Response(), db=db)

            assert exc_info.value.status_code == 401
        finally:
            db.close()
