"""Tests for GET /auth/google/login and GET /auth/google/callback
(app/auth/routers.py::google_login, google_callback).

Google's own HTTP endpoints are mocked -- app.auth.google_oauth's
exchange_code_for_id_token and verify_google_id_token are monkeypatched to
return fixed claims/errors instead of talking to Google. A live Google OAuth
flow is a deliberate separate step once this is reviewed, not exercised
here. The ID token's actual cryptographic verification is covered
separately in test_google_id_token_verification.py.

Router functions are called directly with a real DB session, following the
existing pattern in test_login_rejects_unverified_user.py -- no
TestClient/HTTP layer in this repo's test suite.

Hits the real test Postgres database (docker-compose, see backend/CLAUDE.md)
for User/OAuthState side effects.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from app.auth.google_oauth import GoogleAuthError
from app.auth.models import User
from app.auth.routers import GOOGLE_LOGIN_STATE_PURPOSE, google_callback, google_login
from app.auth.security import hash_password
from app.config import settings
from app.core.oauth_state import OAuthState, create_oauth_state
from app.db.session import SessionLocal

FRESH_EMAIL = "google-sso-fresh-test@example.com"
FRESH_SUB = "google-sub-fresh-000111"

EXISTING_GOOGLE_EMAIL = "google-sso-existing-login-test@example.com"
EXISTING_GOOGLE_SUB = "google-sub-existing-222333"

LINK_VERIFIED_EMAIL = "google-sso-link-verified-test@example.com"
LINK_VERIFIED_SUB = "google-sub-link-verified-444555"

UNVERIFIED_EMAIL_CLAIM_EMAIL = "google-sso-unverified-claim-test@example.com"
UNVERIFIED_EMAIL_CLAIM_SUB = "google-sub-unverified-claim-888999"

REUSE_EMAIL = "google-sso-reuse-test@example.com"
REUSE_SUB = "google-sub-reuse-111222"

ALL_TEST_EMAILS = [
    FRESH_EMAIL,
    EXISTING_GOOGLE_EMAIL,
    LINK_VERIFIED_EMAIL,
    UNVERIFIED_EMAIL_CLAIM_EMAIL,
    REUSE_EMAIL,
]


def _claims(sub: str, email: str, *, name: str | None = "Test User") -> dict:
    return {"sub": sub, "email": email, "email_verified": True, "name": name}


@pytest.fixture
def mock_google(monkeypatch):
    state = {"claims": None, "exchange_error": None, "verify_error": None}

    def _exchange(code):
        if state["exchange_error"] is not None:
            raise state["exchange_error"]
        return "fake-id-token"

    def _verify(id_token_str):
        if state["verify_error"] is not None:
            raise state["verify_error"]
        return state["claims"]

    monkeypatch.setattr("app.auth.google_oauth.exchange_code_for_id_token", _exchange)
    monkeypatch.setattr("app.auth.google_oauth.verify_google_id_token", _verify)
    return state


@pytest.fixture
def clean_test_users():
    db = SessionLocal()
    try:
        db.query(User).filter(User.email.in_(ALL_TEST_EMAILS)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(User).filter(User.email.in_(ALL_TEST_EMAILS)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _create_state(db, *, purpose: str = GOOGLE_LOGIN_STATE_PURPOSE) -> tuple[str, str]:
    token = create_oauth_state(db, purpose=purpose)
    payload = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return token, payload["jti"]


def _delete_state(db, jti: str) -> None:
    db.query(OAuthState).filter(OAuthState.jti == jti).delete()
    db.commit()


class TestGoogleLoginRedirect:
    def test_redirects_with_correct_scopes_and_signed_state(self):
        db = SessionLocal()
        jti = None
        try:
            response = google_login(db=db)

            location = response.headers["location"]
            parsed = urlparse(location)
            assert parsed.netloc == "accounts.google.com"

            query = parse_qs(parsed.query)
            assert query["client_id"][0] == settings.google_client_id
            assert query["redirect_uri"][0] == settings.google_redirect_uri
            assert query["response_type"][0] == "code"
            assert set(query["scope"][0].split()) == {"openid", "email", "profile"}

            state_token = query["state"][0]
            payload = pyjwt.decode(state_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            assert payload["purpose"] == GOOGLE_LOGIN_STATE_PURPOSE
            jti = payload["jti"]

            state_row = db.query(OAuthState).filter(OAuthState.jti == jti).first()
            assert state_row is not None
            assert state_row.used_at is None
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()


class TestGoogleCallbackFreshSignup:
    def test_creates_new_user_with_expected_fields(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        try:
            mock_google["claims"] = _claims(FRESH_SUB, FRESH_EMAIL)
            state_token, jti = _create_state(db)

            response = google_callback(code="fake-code", state=state_token, db=db)

            user = db.query(User).filter(User.email == FRESH_EMAIL).first()
            assert user is not None
            assert user.google_user_id == FRESH_SUB
            assert user.is_sso_user is True
            assert user.is_active is True
            assert user.hashed_password is None
            assert "token=" in response.headers["location"]
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()


class TestGoogleCallbackExistingGoogleLogin:
    def test_login_with_existing_google_user_id_succeeds_without_creating_duplicate(
        self, clean_test_users, mock_google
    ):
        db = SessionLocal()
        jti = None
        try:
            existing = User(
                email=EXISTING_GOOGLE_EMAIL,
                hashed_password=None,
                is_active=True,
                is_sso_user=True,
                google_user_id=EXISTING_GOOGLE_SUB,
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)

            # Claims carry a different email than the DB row -- once linked,
            # lookup must be by google_user_id, not email, so this proves the
            # email in the claims is ignored on subsequent logins.
            mock_google["claims"] = _claims(EXISTING_GOOGLE_SUB, "should-be-ignored@example.com")
            state_token, jti = _create_state(db)

            google_callback(code="fake-code", state=state_token, db=db)

            matches = db.query(User).filter(User.google_user_id == EXISTING_GOOGLE_SUB).all()
            assert len(matches) == 1
            assert matches[0].id == existing.id
            assert matches[0].email == EXISTING_GOOGLE_EMAIL
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()


class TestGoogleCallbackLinksExistingPasswordAccount:
    def test_links_to_existing_verified_account_without_wiping_password(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        try:
            existing = User(
                email=LINK_VERIFIED_EMAIL,
                hashed_password=hash_password("correct-horse-battery"),
                is_active=True,
                is_sso_user=False,
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)
            original_hash = existing.hashed_password

            mock_google["claims"] = _claims(LINK_VERIFIED_SUB, LINK_VERIFIED_EMAIL)
            state_token, jti = _create_state(db)

            google_callback(code="fake-code", state=state_token, db=db)

            db.refresh(existing)
            assert existing.google_user_id == LINK_VERIFIED_SUB
            assert existing.is_sso_user is True
            assert existing.is_active is True
            assert existing.hashed_password == original_hash
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()


class TestGoogleCallbackRejectsUnverifiedEmail:
    def test_email_verified_false_from_google_is_rejected(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        try:
            mock_google["verify_error"] = GoogleAuthError("Google account email is not verified")
            state_token, jti = _create_state(db)

            with pytest.raises(HTTPException) as exc_info:
                google_callback(code="fake-code", state=state_token, db=db)

            assert exc_info.value.status_code == 400
            assert db.query(User).filter(User.email == UNVERIFIED_EMAIL_CLAIM_EMAIL).first() is None
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()


class TestGoogleCallbackStateValidation:
    def test_tampered_state_rejected(self, mock_google):
        db = SessionLocal()
        jti = None
        try:
            state_token, jti = _create_state(db)
            tampered = state_token[:-4] + ("XXXX" if not state_token.endswith("XXXX") else "YYYY")

            with pytest.raises(HTTPException) as exc_info:
                google_callback(code="fake-code", state=tampered, db=db)

            assert exc_info.value.status_code == 400
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()

    def test_expired_state_rejected(self, mock_google):
        db = SessionLocal()
        jti = None
        try:
            import uuid

            jti = uuid.uuid4().hex
            past = datetime.now(timezone.utc) - timedelta(seconds=5)
            db.add(OAuthState(jti=jti, purpose=GOOGLE_LOGIN_STATE_PURPOSE, expires_at=past))
            db.commit()
            token = pyjwt.encode(
                {"jti": jti, "purpose": GOOGLE_LOGIN_STATE_PURPOSE, "exp": past},
                settings.jwt_secret_key,
                algorithm=settings.jwt_algorithm,
            )

            with pytest.raises(HTTPException) as exc_info:
                google_callback(code="fake-code", state=token, db=db)

            assert exc_info.value.status_code == 400
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()

    def test_reused_state_rejected_on_second_use(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        try:
            mock_google["claims"] = _claims(REUSE_SUB, REUSE_EMAIL)
            state_token, jti = _create_state(db)

            google_callback(code="fake-code", state=state_token, db=db)

            with pytest.raises(HTTPException) as exc_info:
                google_callback(code="fake-code", state=state_token, db=db)

            assert exc_info.value.status_code == 400
            assert "already" in exc_info.value.detail.lower()
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()

    def test_wrong_purpose_state_rejected(self, mock_google):
        db = SessionLocal()
        jti = None
        try:
            state_token, jti = _create_state(db, purpose="some_other_purpose")

            with pytest.raises(HTTPException) as exc_info:
                google_callback(code="fake-code", state=state_token, db=db)

            assert exc_info.value.status_code == 400
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()
