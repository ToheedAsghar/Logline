"""Regression test for app/auth/routers.py::login's nullable-password check
(added for Google SSO -- hashed_password is now nullable since a pure
Google-only signup never sets one). A None hashed_password must produce the
exact same 401 + generic message as a wrong password on a normal account --
not a distinguishable error -- so a caller can't use login() to enumerate
which accounts are Google-only.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""
import pytest
from fastapi import HTTPException, Response

from app.auth.constants import TEXT_LOGIN_INVALID_CREDENTIALS
from app.auth.models import User
from app.auth.routers import login
from app.auth.schemas import UserLogin
from app.auth.security import hash_password
from app.db.session import SessionLocal

NULL_PASSWORD_EMAIL = "login-null-password-test@example.com"
WRONG_PASSWORD_EMAIL = "login-wrong-password-oracle-test@example.com"


class TestLoginNullPasswordIsNotADistinguishableOracle:
    def test_null_password_account_gets_401_with_generic_message(self):
        db = SessionLocal()
        try:
            db.query(User).filter(User.email == NULL_PASSWORD_EMAIL).delete()
            db.commit()
            db.add(
                User(
                    email=NULL_PASSWORD_EMAIL,
                    hashed_password=None,
                    is_active=True,
                    is_sso_user=True,
                    google_user_id="google-sub-null-password-test",
                )
            )
            db.commit()

            payload = UserLogin(email=NULL_PASSWORD_EMAIL, password="anything-at-all")
            with pytest.raises(HTTPException) as exc_info:
                login(payload, response=Response(), db=db)

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == TEXT_LOGIN_INVALID_CREDENTIALS
        finally:
            db.query(User).filter(User.email == NULL_PASSWORD_EMAIL).delete()
            db.commit()
            db.close()

    def test_wrong_password_on_normal_account_gets_the_identical_response(self):
        db = SessionLocal()
        try:
            db.query(User).filter(User.email == WRONG_PASSWORD_EMAIL).delete()
            db.commit()
            db.add(
                User(
                    email=WRONG_PASSWORD_EMAIL,
                    hashed_password=hash_password("correct-horse-battery"),
                    is_active=True,
                )
            )
            db.commit()

            payload = UserLogin(email=WRONG_PASSWORD_EMAIL, password="totally-wrong-password")
            with pytest.raises(HTTPException) as exc_info:
                login(payload, response=Response(), db=db)

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == TEXT_LOGIN_INVALID_CREDENTIALS
        finally:
            db.query(User).filter(User.email == WRONG_PASSWORD_EMAIL).delete()
            db.commit()
            db.close()
