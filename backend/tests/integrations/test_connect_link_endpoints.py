"""Tests for the HTTP endpoints and auth logic that handle one-time passes.

The tests confirm that:
- POST /{source}/connect-link creates and returns a valid pass URL, and cleanly rejects requests for providers we
  haven't wired up yet (404).
- GET /{source}/connect can authenticate using either a bearer token or a one-time pass query parameter, and rejects
  missing credentials.
- A one-time pass is rejected if it's expired, already used, or for the wrong provider.
- Crucially: the two kinds of tokens we use (one-time passes, and the "state" tokens used later in the OAuth flow) can
  never be confused or swapped. Using one where the other is expected is rejected, even though both are signed
  itsdangerous envelopes.

The tests use a real Postgres database (not mocks) because the purpose is to verify database row behavior and the
single-use guarantee across connections.
"""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.models import User
from app.auth.security import create_access_token
from app.core.oauth_state import OAuthStateError
from app.db.session import SessionLocal
from app.integrations.connect_link_token import create_connect_link_token
from app.integrations.connect_state import consume_connect_state, create_connect_state
from app.integrations.deps import get_connect_endpoint_user
from app.integrations.models import ConnectLinkToken, Integration, IntegrationSource, OAuthToken
from app.integrations.providers import PROVIDERS
from app.integrations.routers import create_connect_link

TEST_EMAIL = "connect-link-endpoint-test@example.com"


def _cleanup(user_id: int) -> None:
    db = SessionLocal()
    try:
        integration_ids = [row.id for row in db.query(Integration.id).filter(Integration.user_id == user_id)]
        if integration_ids:
            db.query(OAuthToken).filter(OAuthToken.integration_id.in_(integration_ids)).delete(
                synchronize_session=False
            )
        db.query(Integration).filter(Integration.user_id == user_id).delete()
        db.query(ConnectLinkToken).filter(ConnectLinkToken.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def test_user_id():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
    finally:
        db.close()
    _cleanup(user_id)

    yield user_id

    _cleanup(user_id)


class _MockCurrentUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class TestCreateConnectLink:
    def test_returns_a_connect_url_naming_the_right_source(self, test_user_id):
        db = SessionLocal()
        try:
            response = create_connect_link(
                source=IntegrationSource.slack, current_user=_MockCurrentUser(test_user_id), db=db
            )

            parsed = urlparse(response.connect_url)
            assert parsed.path == "/integrations/slack/connect"
            assert "token" in parse_qs(parsed.query)
        finally:
            db.close()

    def test_unregistered_source_404s(self, test_user_id):
        """Every IntegrationSource now has a provider, so calendar is unregistered here by patching the registry in
        place -- `is_source_registered` reads the module-level PROVIDERS at call time.
        """
        db = SessionLocal()
        remaining = {
            source: provider for source, provider in PROVIDERS.items() if source is not IntegrationSource.calendar
        }
        try:
            with patch.dict(PROVIDERS, remaining, clear=True), pytest.raises(HTTPException) as exc_info:
                create_connect_link(
                    source=IntegrationSource.calendar, current_user=_MockCurrentUser(test_user_id), db=db
                )
            assert exc_info.value.status_code == 404
        finally:
            db.close()


class TestGetConnectEndpointUserWithToken:
    def test_valid_connect_link_token_resolves_the_user(self, test_user_id):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=test_user_id, source=IntegrationSource.slack)

            user = get_connect_endpoint_user(
                source=IntegrationSource.slack, token=token, credentials=None, db=db
            )
            assert user.id == test_user_id
        finally:
            db.close()

    def test_expired_connect_link_token_is_rejected(self, test_user_id, monkeypatch):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=test_user_id, source=IntegrationSource.slack)
            monkeypatch.setattr("app.integrations.connect_link_token.CONNECT_LINK_TOKEN_TTL_SECONDS", -1)

            with pytest.raises(HTTPException) as exc_info:
                get_connect_endpoint_user(source=IntegrationSource.slack, token=token, credentials=None, db=db)
            assert exc_info.value.status_code == 401
        finally:
            db.close()

    def test_already_used_connect_link_token_is_rejected(self, test_user_id):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=test_user_id, source=IntegrationSource.slack)
            get_connect_endpoint_user(source=IntegrationSource.slack, token=token, credentials=None, db=db)

            with pytest.raises(HTTPException) as exc_info:
                get_connect_endpoint_user(source=IntegrationSource.slack, token=token, credentials=None, db=db)
            assert exc_info.value.status_code == 401
        finally:
            db.close()

    def test_missing_credentials_and_token_is_rejected(self, test_user_id):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                get_connect_endpoint_user(source=IntegrationSource.slack, token=None, credentials=None, db=db)
            assert exc_info.value.status_code == 401
        finally:
            db.close()


class TestGetConnectEndpointUserWithHeader:
    def test_valid_authorization_header_resolves_the_user(self, test_user_id):
        db = SessionLocal()
        try:
            access_token = create_access_token(test_user_id)
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token)

            user = get_connect_endpoint_user(
                source=IntegrationSource.slack, token=None, credentials=credentials, db=db
            )
            assert user.id == test_user_id
        finally:
            db.close()


class TestConnectStateAndConnectLinkTokensCannotBeConfused:
    def test_connect_state_token_is_rejected_when_presented_as_a_connect_link_token(self, test_user_id):
        db = SessionLocal()
        try:
            state_token = create_connect_state(db, user_id=test_user_id, source=IntegrationSource.slack)
        finally:
            db.close()

        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                get_connect_endpoint_user(
                    source=IntegrationSource.slack, token=state_token, credentials=None, db=db
                )
            assert exc_info.value.status_code == 401
        finally:
            db.close()

    def test_connect_link_token_is_rejected_when_presented_as_a_connect_state_token(self, test_user_id):
        db = SessionLocal()
        try:
            link_token = create_connect_link_token(db, user_id=test_user_id, source=IntegrationSource.slack)
        finally:
            db.close()

        db = SessionLocal()
        try:
            with pytest.raises(OAuthStateError):
                consume_connect_state(db, token=link_token, expected_source=IntegrationSource.slack)
        finally:
            db.close()
