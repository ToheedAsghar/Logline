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
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt as pyjwt
import pytest
from fastapi import HTTPException, Response

from app.auth import crud
from app.auth.constants import GOOGLE_LOGIN_STATE_PURPOSE, TEXT_GOOGLE_SIGN_IN_FAILED, TEXT_LOGIN_INVALID_CREDENTIALS
from app.auth.google_oauth import GoogleAuthError
from app.auth.models import User, UserSession
from app.auth.routers import google_callback, google_exchange, google_login, login
from app.auth.schemas import OAuthExchangeRequest, UserLogin
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

LINK_UNVERIFIED_EMAIL = "google-sso-link-unverified-test@example.com"
LINK_UNVERIFIED_SUB = "google-sub-link-unverified-666777"

UNVERIFIED_EMAIL_CLAIM_EMAIL = "google-sso-unverified-claim-test@example.com"
UNVERIFIED_EMAIL_CLAIM_SUB = "google-sub-unverified-claim-888999"

REUSE_EMAIL = "google-sso-reuse-test@example.com"
REUSE_SUB = "google-sub-reuse-111222"

CONCURRENT_SIGNUP_EMAIL = "google-sso-concurrent-signup-test@example.com"
CONCURRENT_SIGNUP_SUB = "google-sub-concurrent-signup-333444"

ALL_TEST_EMAILS = [
    FRESH_EMAIL,
    EXISTING_GOOGLE_EMAIL,
    LINK_VERIFIED_EMAIL,
    LINK_UNVERIFIED_EMAIL,
    UNVERIFIED_EMAIL_CLAIM_EMAIL,
    REUSE_EMAIL,
    CONCURRENT_SIGNUP_EMAIL,
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
        db.query(UserSession).filter(
            UserSession.user_id.in_(db.query(User.id).filter(User.email.in_(ALL_TEST_EMAILS)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.email.in_(ALL_TEST_EMAILS)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(UserSession).filter(
            UserSession.user_id.in_(db.query(User.id).filter(User.email.in_(ALL_TEST_EMAILS)))
        ).delete(synchronize_session=False)
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
            assert "code=" in response.headers["location"]
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

    def test_links_to_existing_unverified_account_and_activates_it(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        try:
            existing = User(
                email=LINK_UNVERIFIED_EMAIL,
                hashed_password=hash_password("correct-horse-battery"),
                is_active=False,
                is_sso_user=False,
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)

            mock_google["claims"] = _claims(LINK_UNVERIFIED_SUB, LINK_UNVERIFIED_EMAIL)
            state_token, jti = _create_state(db)

            google_callback(code="fake-code", state=state_token, db=db)

            db.refresh(existing)
            assert existing.google_user_id == LINK_UNVERIFIED_SUB
            assert existing.is_sso_user is True
            assert existing.is_active is True
            # Unproven password from the pre-activation row must be discarded
            # -- see test_login_null_password_oracle.py for the attack this
            # closes (pre-registering a victim's email to inherit the
            # account once their Google login activates it).
            assert existing.hashed_password is None
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()

    def test_attacker_password_on_preregistered_email_stops_working_after_victim_links_google(
        self, clean_test_users, mock_google
    ):
        """End-to-end account-pre-hijacking scenario: an attacker
        pre-registers the victim's email with a password only the attacker
        knows, leaving the account unverified. The real victim later signs
        in with Google using that same email, linking and activating the
        account. The attacker's original password must no longer grant
        login -- only Google login (or a fresh password reset) should.
        """
        db = SessionLocal()
        jti = None
        try:
            attacker_password = "attacker-chosen-password"
            preregistered = User(
                email=LINK_UNVERIFIED_EMAIL,
                hashed_password=hash_password(attacker_password),
                is_active=False,
                is_sso_user=False,
            )
            db.add(preregistered)
            db.commit()
            db.refresh(preregistered)

            mock_google["claims"] = _claims(LINK_UNVERIFIED_SUB, LINK_UNVERIFIED_EMAIL)
            state_token, jti = _create_state(db)

            google_callback(code="fake-code", state=state_token, db=db)

            db.refresh(preregistered)
            assert preregistered.is_active is True
            assert preregistered.hashed_password is None

            with pytest.raises(HTTPException) as exc_info:
                login(UserLogin(email=LINK_UNVERIFIED_EMAIL, password=attacker_password), response=Response(), db=db)
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == TEXT_LOGIN_INVALID_CREDENTIALS
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


class TestCreateGoogleUserConcurrentSignup:
    """Two near-simultaneous requests for a brand-new Google account both
    pass the caller's "no existing user" lookup before either commits.
    crud.create_google_user must handle the resulting unique-constraint
    IntegrityError by re-querying for the row the winning request created,
    rather than letting the loser crash -- see crud.py.
    """

    def test_concurrent_create_for_same_new_account_yields_one_row_no_crash(self, clean_test_users):
        results = []
        errors = []
        ready = threading.Barrier(2)

        def worker():
            db = SessionLocal()
            try:
                ready.wait(timeout=5)
                user = crud.create_google_user(
                    db, email=CONCURRENT_SIGNUP_EMAIL, google_user_id=CONCURRENT_SIGNUP_SUB, name="Concurrent"
                )
                results.append(user.id)
            except Exception as exc:
                errors.append(exc)
            finally:
                db.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"concurrent create_google_user raised: {errors}"
        assert len(results) == 2
        assert results[0] == results[1], "both callers must resolve to the same row"

        db = SessionLocal()
        try:
            matches = db.query(User).filter(User.google_user_id == CONCURRENT_SIGNUP_SUB).all()
            assert len(matches) == 1
        finally:
            db.close()


class TestGoogleCallbackErrorMessageSanitization:
    """GoogleAuthError text can embed library/internal failure detail. That
    must never reach the client -- only the generic message -- while the
    real reason still lands in the server log for debugging. See routers.py
    and google_oauth.py.
    """

    def test_client_response_has_generic_message_not_raw_exception_text(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        raw_detail = "authlib internal failure: signature mismatch for kid=xyz123"
        try:
            mock_google["verify_error"] = GoogleAuthError(raw_detail)
            state_token, jti = _create_state(db)

            with pytest.raises(HTTPException) as exc_info:
                google_callback(code="fake-code", state=state_token, db=db)

            assert exc_info.value.status_code == 400
            assert exc_info.value.detail == TEXT_GOOGLE_SIGN_IN_FAILED
            assert raw_detail not in exc_info.value.detail
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()

    def test_raw_exception_text_still_logged_server_side(self, clean_test_users, mock_google, caplog):
        db = SessionLocal()
        jti = None
        raw_detail = "authlib internal failure: signature mismatch for kid=xyz123"
        try:
            mock_google["verify_error"] = GoogleAuthError(raw_detail)
            state_token, jti = _create_state(db)

            with caplog.at_level("INFO"):
                with pytest.raises(HTTPException):
                    google_callback(code="fake-code", state=state_token, db=db)

            assert raw_detail in caplog.text
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()


class TestGoogleCallbackConsentCancellation:
    def test_canceling_consent_returns_clean_400(self, clean_test_users):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                google_callback(error="access_denied", state="fake-state", db=db)
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail == TEXT_GOOGLE_SIGN_IN_FAILED
        finally:
            db.close()


class TestGoogleCallbackInactiveUserCheck:
    def test_inactive_user_rejected_with_403(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        try:
            inactive = User(
                email=FRESH_EMAIL,
                hashed_password=None,
                is_active=False,
                is_sso_user=True,
                google_user_id=FRESH_SUB,
            )
            db.add(inactive)
            db.commit()

            mock_google["claims"] = _claims(FRESH_SUB, FRESH_EMAIL)
            state_token, jti = _create_state(db)

            with pytest.raises(HTTPException) as exc_info:
                google_callback(code="fake-code", state=state_token, db=db)
            assert exc_info.value.status_code == 403
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()


class TestGoogleExchangeCodeEndpoint:
    def test_successful_code_exchange_returns_access_token(self, clean_test_users, mock_google):
        db = SessionLocal()
        jti = None
        try:
            mock_google["claims"] = _claims(FRESH_SUB, FRESH_EMAIL)
            state_token, jti = _create_state(db)

            response = google_callback(code="fake-code", state=state_token, db=db)
            parsed_url = urlparse(response.headers["location"])
            exchange_code = parsed_url.fragment.removeprefix("code=")

            token_res = google_exchange(payload=OAuthExchangeRequest(code=exchange_code), response=Response(), db=db)
            assert token_res.access_token is not None
            assert token_res.token_type == "bearer"
        finally:
            if jti is not None:
                _delete_state(db, jti)
            db.close()
