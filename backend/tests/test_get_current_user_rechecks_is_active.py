"""Tests for app/auth/deps.py::get_current_user re-checking `is_active` on
every request, not just at token-issue time. Before this fix, a validly
signed, unexpired JWT stayed usable for its full lifetime (up to
JWT_EXPIRE_MINUTES) even after the account behind it was deactivated --
there's no token revocation list, so `is_active` re-checking is the only
thing standing between "account deactivated" and "existing sessions keep
working regardless". This closes that gap at the account level; it does NOT
provide per-token revocation (see the comment in get_current_user).

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md).
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.deps import get_current_user
from app.auth.models import User
from app.auth.security import create_access_token
from app.db.session import SessionLocal

TEST_EMAIL = "get-current-user-is-active-recheck-test@example.com"


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture
def active_user():
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == TEST_EMAIL).delete()
        db.commit()
        user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestGetCurrentUserRechecksIsActive:
    def test_active_user_with_valid_token_succeeds(self, active_user):
        token = create_access_token(active_user)
        db = SessionLocal()
        try:
            user = get_current_user(credentials=_credentials(token), db=db)
            assert user.id == active_user
        finally:
            db.close()

    def test_token_issued_while_active_is_rejected_once_account_is_deactivated(self, active_user):
        # The token is still validly signed and unexpired -- only the
        # account's is_active flag changes between issuance and use.
        token = create_access_token(active_user)

        db = SessionLocal()
        try:
            db.query(User).filter(User.id == active_user).update({"is_active": False})
            db.commit()
        finally:
            db.close()

        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(credentials=_credentials(token), db=db)
            assert exc_info.value.status_code == 401
        finally:
            db.close()
