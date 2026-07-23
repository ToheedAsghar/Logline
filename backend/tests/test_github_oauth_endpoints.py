"""Tests for the generic OAuth connect and callback endpoints with GitHub.

These tests verify the same properties that test_oauth_connect_callback_endpoints.py
already verified for Slack: state validation, token storage, error handling.
By running them again for GitHub, we confirm the generic routes (the ones
shared by all providers) work correctly with a second provider without needing
any changes to the shared code.

Like test_oauth_connect_callback_endpoints.py: the tests call router functions directly
with a real test database. GitHub's HTTP API is mocked at the provider level
so no real network calls are made. GitHub-specific behavior (its scopes, error
codes) is tested here too.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

from app.auth.models import User
from app.config import settings
from app.core.oauth_state import OAuthState, OAuthStateError
from app.db.session import SessionLocal, engine
from app.integrations.connect_state import CONNECT_STATE_SALT, consume_connect_state, create_connect_state
from app.integrations.constants import GITHUB_OAUTH_ACCESS_DENIED_MESSAGE
from app.integrations.models import Integration, IntegrationSource, IntegrationStatus, OAuthToken
from app.integrations.providers.base import OAuthTokens
from app.integrations.providers.github import GitHubOAuthError, GitHubOAuthProvider
from app.integrations.routers import connect_integration, integration_callback

TEST_EMAIL = "github-oauth-endpoint-test@example.com"


@pytest.fixture(scope="module", autouse=True)
def _require_oauth_states_table():
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
        token = create_connect_state(db, user_id=user_id, source=IntegrationSource.github)
    finally:
        db.close()
    return token


def _decode_inner_jti(state_token: str) -> str:
    envelope = URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=CONNECT_STATE_SALT)
    inner_token = envelope.loads(state_token)["inner_token"]
    payload = jwt.decode(inner_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return payload["jti"]


def _patch_exchange(**kwargs):
    return patch.object(GitHubOAuthProvider, "exchange_code", AsyncMock(**kwargs))


class TestConnectIntegration:
    def test_redirects_to_github_authorize_url_with_correct_scopes_and_valid_state(self, test_user_id):
        db = SessionLocal()
        try:
            response = connect_integration(
                source=IntegrationSource.github, current_user=MagicMock(id=test_user_id), db=db
            )

            assert response.status_code in (302, 307)
            location = response.headers["location"]
            parsed = urlparse(location)
            assert (
                f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                == "https://github.com/login/oauth/authorize"
            )

            query = parse_qs(parsed.query)
            assert query["scope"] == ["repo"]

            user_id = consume_connect_state(
                db, token=query["state"][0], expected_source=IntegrationSource.github
            )
            assert user_id == test_user_id
        finally:
            db.close()


class TestIntegrationCallback:
    def test_successful_exchange_stores_encrypted_tokens_and_redirects_connected(self, test_user_id):
        state = _issue_state(test_user_id)
        fake_tokens = OAuthTokens(access_token="gho_plaintext-access-token")

        db = SessionLocal()
        try:
            with _patch_exchange(return_value=fake_tokens):
                response = asyncio.run(
                    integration_callback(source=IntegrationSource.github, code="good-code", state=state, db=db)
                )

            assert response.status_code in (302, 307)
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["connected"]
            assert query["integration"] == ["github"]

            integration = (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.github,
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
            assert token_row.access_token == "gho_plaintext-access-token"
            assert token_row.refresh_token is None

            raw_row = db.execute(
                text("SELECT access_token FROM oauth_tokens WHERE id = :id"),
                {"id": token_row.id},
            ).first()
        finally:
            db.close()
        assert "gho_plaintext-access-token" not in raw_row.access_token

    def test_reconnecting_updates_the_same_integration_and_token_row(self, test_user_id):
        state_one = _issue_state(test_user_id)
        db = SessionLocal()
        try:
            with _patch_exchange(return_value=OAuthTokens(access_token="first-token")):
                asyncio.run(
                    integration_callback(source=IntegrationSource.github, code="code-1", state=state_one, db=db)
                )
        finally:
            db.close()

        state_two = _issue_state(test_user_id)
        db = SessionLocal()
        try:
            with _patch_exchange(return_value=OAuthTokens(access_token="second-token")):
                asyncio.run(
                    integration_callback(source=IntegrationSource.github, code="code-2", state=state_two, db=db)
                )

            integrations = (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.github,
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
        mid = len(state) // 2
        tampered = state[:mid] + ("A" if state[mid] != "A" else "B") + state[mid + 1 :]

        db = SessionLocal()
        try:
            response = asyncio.run(
                integration_callback(source=IntegrationSource.github, code="some-code", state=tampered, db=db)
            )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.github,
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
                    integration_callback(source=IntegrationSource.github, code="code-1", state=state, db=db)
                )
            assert parse_qs(urlparse(first.headers["location"]).query)["status"] == ["connected"]

            with _patch_exchange() as mock_exchange:
                second = asyncio.run(
                    integration_callback(source=IntegrationSource.github, code="code-2", state=state, db=db)
                )

            mock_exchange.assert_not_called()
            assert parse_qs(urlparse(second.headers["location"]).query)["status"] == ["error"]
        finally:
            db.close()

    def test_github_denial_redirects_with_error_and_durably_consumes_state(self, test_user_id):
        state = _issue_state(test_user_id)
        jti = _decode_inner_jti(state)

        db = SessionLocal()
        try:
            response = asyncio.run(
                integration_callback(
                    source=IntegrationSource.github, code=None, state=state, error="access_denied", db=db
                )
            )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
            assert query["detail"] == [GITHUB_OAUTH_ACCESS_DENIED_MESSAGE]
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
                consume_connect_state(replay_db, token=state, expected_source=IntegrationSource.github)
        finally:
            replay_db.close()

    def test_state_issued_for_a_different_provider_is_rejected(self, test_user_id):
        """State tokens are bound to a specific provider. A state token created
        for Slack's connect flow cannot be reused in GitHub's callback, even
        though both providers use the same generic routes. This prevents someone
        from redirecting a user from a Slack auth flow to a GitHub callback.
        """
        db = SessionLocal()
        try:
            slack_state = create_connect_state(db, user_id=test_user_id, source=IntegrationSource.slack)
        finally:
            db.close()

        db = SessionLocal()
        try:
            with _patch_exchange() as mock_exchange:
                response = asyncio.run(
                    integration_callback(
                        source=IntegrationSource.github, code="some-code", state=slack_state, db=db
                    )
                )

            mock_exchange.assert_not_called()
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.github,
                )
                .first()
                is None
            )
            assert (
                db.query(OAuthToken)
                .join(Integration, OAuthToken.integration_id == Integration.id)
                .filter(Integration.user_id == test_user_id)
                .first()
                is None
            )
        finally:
            db.close()

    def test_missing_code_or_state_redirects_with_error(self):
        db = SessionLocal()
        try:
            response = asyncio.run(integration_callback(source=IntegrationSource.github, db=db))
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
        finally:
            db.close()

    def test_failed_github_exchange_redirects_with_informative_error_and_writes_nothing(self, test_user_id):
        state = _issue_state(test_user_id)

        db = SessionLocal()
        try:
            with _patch_exchange(
                side_effect=GitHubOAuthError(
                    "GitHub rejected the access_token request: bad_verification_code"
                )
            ):
                response = asyncio.run(
                    integration_callback(source=IntegrationSource.github, code="bad-code", state=state, db=db)
                )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
            assert "bad_verification_code" in query["detail"][0]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.github,
                )
                .first()
                is None
            )
        finally:
            db.close()
