"""Tests for the generic OAuth connect and callback endpoints, exercised for
Slack (the one registered provider).

These tests call the router functions directly (rather than via HTTP) with a
real database session. Slack's API is mocked -- we test the flow logic, not
real Slack responses. The tests verify that tokens are stored correctly,
state validation works, and errors are handled properly. Every security
property previously verified against the dedicated /slack/* routes is
re-verified here against the generic /{source}/* routes, proving the
provider-agnostic refactor did not regress anything.

The test database is real Postgres (via docker-compose) to ensure that the
database changes (storing tokens, marking state as used) persist correctly.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import HTTPException
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

from app.auth.models import User
from app.config import settings
from app.core.oauth_state import OAuthState, OAuthStateError
from app.db.session import SessionLocal, engine
from app.integrations.connect_state import CONNECT_STATE_SALT, consume_connect_state, create_connect_state
from app.integrations.constants import SLACK_OAUTH_ACCESS_DENIED_MESSAGE, SLACK_OAUTH_USER_SCOPES
from app.integrations.models import Integration, IntegrationSource, IntegrationStatus, OAuthToken
from app.integrations.providers.base import OAuthTokens
from app.integrations.providers.slack import SlackOAuthError, SlackOAuthProvider
from app.integrations.routers import connect_integration, integration_callback

TEST_EMAIL = "slack-oauth-endpoint-test@example.com"


@pytest.fixture(scope="module", autouse=True)
def _require_oauth_states_table():
    """Check that the oauth_states table exists before running tests.
    Fail loudly if it's missing -- this means a database migration wasn't
    applied, which needs to be fixed before running tests.
    """
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass('public.oauth_states') IS NOT NULL")
        ).scalar_one()
    if not exists:
        pytest.fail(
            "oauth_states table does not exist -- run `alembic upgrade head` "
            "before running this test module."
        )


def _cleanup(user_id: int) -> None:
    db = SessionLocal()
    try:
        integration_ids = [
            row.id
            for row in db.query(Integration.id).filter(Integration.user_id == user_id)
        ]
        if integration_ids:
            db.query(OAuthToken).filter(
                OAuthToken.integration_id.in_(integration_ids)
            ).delete(synchronize_session=False)
        db.query(Integration).filter(Integration.user_id == user_id).delete()
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


def _issue_state(user_id: int) -> str:
    db = SessionLocal()
    try:
        token = create_connect_state(db, user_id=user_id, source=IntegrationSource.slack)
    finally:
        db.close()
    return token


def _decode_inner_jti(state_token: str) -> str:
    """Extract the jti (unique ID) from a state token by unwrapping both
    the outer signed envelope and the inner JWT. This lets tests query the
    oauth_states table directly to verify that token consumption is
    permanently saved to the database (not just in memory).
    """
    envelope = URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=CONNECT_STATE_SALT)
    inner_token = envelope.loads(state_token)["inner_token"]
    payload = jwt.decode(inner_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return payload["jti"]


def _patch_exchange(**kwargs):
    """Patch the Slack provider's exchange_code -- the seam the generic
    callback route now calls instead of a module-level function."""
    return patch.object(SlackOAuthProvider, "exchange_code", AsyncMock(**kwargs))


class TestConnectIntegration:
    def test_redirects_to_slack_authorize_url_with_correct_scopes_and_valid_state(self, test_user_id):
        db = SessionLocal()
        try:
            response = connect_integration(
                source=IntegrationSource.slack, current_user=MagicMock(id=test_user_id), db=db
            )

            assert response.status_code in (302, 307)
            location = response.headers["location"]
            parsed = urlparse(location)
            assert (
                f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                == "https://slack.com/oauth/v2/authorize"
            )

            query = parse_qs(parsed.query)
            assert query["user_scope"] == [",".join(SLACK_OAUTH_USER_SCOPES)]
            assert "im:history" not in query["user_scope"][0].split(",")

            user_id = consume_connect_state(
                db, token=query["state"][0], expected_source=IntegrationSource.slack
            )
            assert user_id == test_user_id
        finally:
            db.close()


class TestUnregisteredSource:
    """A valid IntegrationSource with no registered provider (jira/github/
    calendar today) must be rejected cleanly with a 404, never a 500 or a
    partially-run flow."""

    def test_connect_unregistered_source_404s(self, test_user_id):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                connect_integration(
                    source=IntegrationSource.jira, current_user=MagicMock(id=test_user_id), db=db
                )
            assert exc_info.value.status_code == 404
        finally:
            db.close()

    def test_callback_unregistered_source_404s(self):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    integration_callback(source=IntegrationSource.github, code="x", state="y", db=db)
                )
            assert exc_info.value.status_code == 404
        finally:
            db.close()


class TestIntegrationCallback:
    def test_successful_exchange_stores_encrypted_tokens_and_redirects_connected(self, test_user_id):
        """Checks both ends of storage: the ORM-decrypted value matches what
        was exchanged (round trip works), and the raw column value read via
        plain textual SQL -- which bypasses EncryptedString's result
        processing -- does not contain the plaintext (it's actually
        encrypted at rest, not stored as-is)."""
        state = _issue_state(test_user_id)
        fake_tokens = OAuthTokens(
            access_token="xoxp-plaintext-access-token",
            refresh_token="xoxe-plaintext-refresh-token",
            authed_user_id="U123",
        )

        db = SessionLocal()
        try:
            with _patch_exchange(return_value=fake_tokens):
                response = asyncio.run(
                    integration_callback(source=IntegrationSource.slack, code="good-code", state=state, db=db)
                )

            assert response.status_code in (302, 307)
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["connected"]
            assert query["integration"] == ["slack"]

            integration = (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.slack,
                )
                .first()
            )
            assert integration is not None
            assert integration.status == IntegrationStatus.connected

            token_row = (
                db.query(OAuthToken)
                .filter(OAuthToken.integration_id == integration.id)
                .first()
            )
            assert token_row is not None
            assert token_row.access_token == "xoxp-plaintext-access-token"
            assert token_row.refresh_token == "xoxe-plaintext-refresh-token"

            raw_row = db.execute(
                text("SELECT access_token FROM oauth_tokens WHERE id = :id"),
                {"id": token_row.id},
            ).first()
        finally:
            db.close()
        assert "xoxp-plaintext-access-token" not in raw_row.access_token

    def test_reconnecting_updates_the_same_integration_and_token_row(self, test_user_id):
        state_one = _issue_state(test_user_id)
        db = SessionLocal()
        try:
            with _patch_exchange(return_value=OAuthTokens(access_token="first-token")):
                asyncio.run(
                    integration_callback(source=IntegrationSource.slack, code="code-1", state=state_one, db=db)
                )
        finally:
            db.close()

        state_two = _issue_state(test_user_id)
        db = SessionLocal()
        try:
            with _patch_exchange(return_value=OAuthTokens(access_token="second-token")):
                asyncio.run(
                    integration_callback(source=IntegrationSource.slack, code="code-2", state=state_two, db=db)
                )

            integrations = (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.slack,
                )
                .all()
            )
            assert len(integrations) == 1
            tokens = (
                db.query(OAuthToken)
                .filter(OAuthToken.integration_id == integrations[0].id)
                .all()
            )
            assert len(tokens) == 1
            assert tokens[0].access_token == "second-token"
        finally:
            db.close()

    def test_tampered_state_redirects_with_error_and_writes_nothing(self, test_user_id):
        state = _issue_state(test_user_id)
        # Change a character in the middle (not the last one, to avoid
        # base64 padding edge cases that could make the test flaky).
        mid = len(state) // 2
        tampered = state[:mid] + ("A" if state[mid] != "A" else "B") + state[mid + 1 :]

        db = SessionLocal()
        try:
            response = asyncio.run(
                integration_callback(source=IntegrationSource.slack, code="some-code", state=tampered, db=db)
            )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.slack,
                )
                .first()
                is None
            )
        finally:
            db.close()

    def test_reused_state_is_rejected_on_second_callback(self, test_user_id):
        state = _issue_state(test_user_id)
        db = SessionLocal()
        try:
            with _patch_exchange(return_value=OAuthTokens(access_token="first-use-token")):
                first = asyncio.run(
                    integration_callback(source=IntegrationSource.slack, code="code-1", state=state, db=db)
                )
            assert parse_qs(urlparse(first.headers["location"]).query)["status"] == ["connected"]

            with _patch_exchange() as mock_exchange:
                second = asyncio.run(
                    integration_callback(source=IntegrationSource.slack, code="code-2", state=state, db=db)
                )

            mock_exchange.assert_not_called()
            assert parse_qs(urlparse(second.headers["location"]).query)["status"] == ["error"]
        finally:
            db.close()

    def test_slack_denial_redirects_with_error_and_durably_consumes_state(self, test_user_id):
        """Tests that Slack denials (with error but no code) are handled
        correctly: the error is mapped to a user-friendly message, and the
        state token is permanently marked as consumed in the database so
        it can't be reused.
        """
        state = _issue_state(test_user_id)
        jti = _decode_inner_jti(state)

        db = SessionLocal()
        try:
            response = asyncio.run(
                integration_callback(
                    source=IntegrationSource.slack, code=None, state=state, error="access_denied", db=db
                )
            )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
            assert query["detail"] == [SLACK_OAUTH_ACCESS_DENIED_MESSAGE]
            assert "access_denied" not in query["detail"][0]
        finally:
            db.close()

        verify_db = SessionLocal()
        try:
            row = verify_db.query(OAuthState).filter(OAuthState.jti == jti).first()
            assert row is not None
            assert row.used_at is not None
        finally:
            verify_db.close()

        replay_db = SessionLocal()
        try:
            with pytest.raises(OAuthStateError):
                consume_connect_state(replay_db, token=state, expected_source=IntegrationSource.slack)
        finally:
            replay_db.close()

    def test_slack_denial_with_stray_code_still_hits_denial_branch(self, test_user_id):
        """Ensures that if both error and code are present (shouldn't
        happen with real Slack), the error is handled instead of attempting
        a token exchange.
        """
        state = _issue_state(test_user_id)

        db = SessionLocal()
        try:
            with _patch_exchange() as mock_exchange:
                response = asyncio.run(
                    integration_callback(
                        source=IntegrationSource.slack, code="stray-code", state=state, error="access_denied", db=db
                    )
                )

            mock_exchange.assert_not_called()
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
            assert query["detail"] == [SLACK_OAUTH_ACCESS_DENIED_MESSAGE]
        finally:
            db.close()

    def test_missing_code_or_state_redirects_with_error(self):
        db = SessionLocal()
        try:
            response = asyncio.run(integration_callback(source=IntegrationSource.slack, db=db))
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
        finally:
            db.close()

    def test_failed_slack_exchange_redirects_with_informative_error_and_writes_nothing(self, test_user_id):
        state = _issue_state(test_user_id)

        db = SessionLocal()
        try:
            with _patch_exchange(
                side_effect=SlackOAuthError(
                    "Slack rejected the oauth.v2.access request: invalid_code"
                )
            ):
                response = asyncio.run(
                    integration_callback(source=IntegrationSource.slack, code="bad-code", state=state, db=db)
                )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
            assert "invalid_code" in query["detail"][0]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.slack,
                )
                .first()
                is None
            )
        finally:
            db.close()
