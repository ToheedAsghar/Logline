"""Tests for the generic OAuth connect and callback endpoints with Jira.

These tests verify the same properties that test_oauth_connect_callback_endpoints.py and
test_github_oauth_endpoints.py already verified for their providers: state
validation, token storage, error handling. By running them again for Jira, we
confirm the generic routes (the ones shared by all providers) work correctly
with a third provider without needing any changes to the shared code.

Like the other two: the tests call router functions directly with a real test
database. Jira's HTTP API is mocked at the provider level so no real network
calls are made. Jira-specific behavior (its scopes, error codes) is tested
here too.
"""

import asyncio
from datetime import datetime, timedelta, timezone
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
from app.integrations.constants import JIRA_OAUTH_ACCESS_DENIED_MESSAGE
from app.integrations.models import Integration, IntegrationSource, IntegrationStatus, OAuthToken
from app.integrations.providers.base import OAuthTokens
from app.integrations.providers.github import GitHubOAuthProvider
from app.integrations.providers.jira import JiraOAuthError, JiraOAuthProvider
from app.integrations.routers import connect_integration, integration_callback
from app.integrations.token_refresh import ensure_token_fresh

TEST_EMAIL = "jira-oauth-endpoint-test@example.com"

#: jtis of every connect-state this module issues, so cleanup can purge the
#: oauth_states rows they leave behind. OAuthState has no user_id column
#: (deliberately -- see app/core/oauth_state.py), so those rows can't be
#: deleted by user like integrations/tokens are; we track and delete by jti.
_issued_state_jtis: list[str] = []


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

        # oauth_states rows are user-agnostic, so purge them by the jtis this
        # module issued rather than by user_id -- otherwise they accumulate
        # indefinitely in the shared dev DB.
        if _issued_state_jtis:
            db.query(OAuthState).filter(
                OAuthState.jti.in_(_issued_state_jtis)
            ).delete(synchronize_session=False)
            _issued_state_jtis.clear()
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


def _decode_inner_jti(state_token: str) -> str:
    envelope = URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=CONNECT_STATE_SALT)
    inner_token = envelope.loads(state_token)["inner_token"]
    payload = jwt.decode(inner_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return payload["jti"]


def _track_state(state_token: str) -> str:
    """Record the jti of a freshly issued connect-state so _cleanup can delete
    its oauth_states row afterward. Returns the token unchanged for chaining."""
    _issued_state_jtis.append(_decode_inner_jti(state_token))
    return state_token


def _issue_state(user_id: int, source: IntegrationSource = IntegrationSource.jira) -> str:
    db = SessionLocal()
    try:
        token = create_connect_state(db, user_id=user_id, source=source)
    finally:
        db.close()
    return _track_state(token)


def _patch_exchange(**kwargs):
    return patch.object(JiraOAuthProvider, "exchange_code", AsyncMock(**kwargs))


class TestConnectIntegration:
    def test_redirects_to_jira_authorize_url_with_correct_scopes_and_valid_state(self, test_user_id):
        db = SessionLocal()
        try:
            response = connect_integration(
                source=IntegrationSource.jira, current_user=MagicMock(id=test_user_id), db=db
            )

            assert response.status_code in (302, 307)
            location = response.headers["location"]
            parsed = urlparse(location)
            assert (
                f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                == "https://auth.atlassian.com/authorize"
            )

            query = parse_qs(parsed.query)
            assert query["scope"] == ["read:jira-work read:jira-user offline_access"]
            assert query["audience"] == ["api.atlassian.com"]

            _track_state(query["state"][0])
            user_id = consume_connect_state(
                db, token=query["state"][0], expected_source=IntegrationSource.jira
            )
            assert user_id == test_user_id
        finally:
            db.close()


class TestIntegrationCallback:
    def test_successful_exchange_stores_encrypted_tokens_and_redirects_connected(self, test_user_id):
        state = _issue_state(test_user_id)
        fake_tokens = OAuthTokens(
            access_token="jira-plaintext-access-token", refresh_token="jira-plaintext-refresh-token"
        )

        db = SessionLocal()
        try:
            with _patch_exchange(return_value=fake_tokens):
                response = asyncio.run(
                    integration_callback(source=IntegrationSource.jira, code="good-code", state=state, db=db)
                )

            assert response.status_code in (302, 307)
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["connected"]
            assert query["integration"] == ["jira"]

            integration = (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.jira,
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
            assert token_row.access_token == "jira-plaintext-access-token"
            assert token_row.refresh_token == "jira-plaintext-refresh-token"

            raw_row = db.execute(
                text("SELECT access_token, refresh_token FROM oauth_tokens WHERE id = :id"),
                {"id": token_row.id},
            ).first()
        finally:
            db.close()
        assert "jira-plaintext-access-token" not in raw_row.access_token
        assert "jira-plaintext-refresh-token" not in raw_row.refresh_token

    def test_reconnecting_updates_the_same_integration_and_token_row(self, test_user_id):
        state_one = _issue_state(test_user_id)
        db = SessionLocal()
        try:
            with _patch_exchange(return_value=OAuthTokens(access_token="first-token")):
                asyncio.run(
                    integration_callback(source=IntegrationSource.jira, code="code-1", state=state_one, db=db)
                )
        finally:
            db.close()

        state_two = _issue_state(test_user_id)
        db = SessionLocal()
        try:
            with _patch_exchange(return_value=OAuthTokens(access_token="second-token")):
                asyncio.run(
                    integration_callback(source=IntegrationSource.jira, code="code-2", state=state_two, db=db)
                )

            integrations = (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.jira,
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
                integration_callback(source=IntegrationSource.jira, code="some-code", state=tampered, db=db)
            )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.jira,
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
                    integration_callback(source=IntegrationSource.jira, code="code-1", state=state, db=db)
                )
            assert parse_qs(urlparse(first.headers["location"]).query)["status"] == ["connected"]

            with _patch_exchange() as mock_exchange:
                second = asyncio.run(
                    integration_callback(source=IntegrationSource.jira, code="code-2", state=state, db=db)
                )

            mock_exchange.assert_not_called()
            assert parse_qs(urlparse(second.headers["location"]).query)["status"] == ["error"]
        finally:
            db.close()

    def test_jira_denial_redirects_with_error_and_durably_consumes_state(self, test_user_id):
        state = _issue_state(test_user_id)
        jti = _decode_inner_jti(state)

        db = SessionLocal()
        try:
            response = asyncio.run(
                integration_callback(
                    source=IntegrationSource.jira, code=None, state=state, error="access_denied", db=db
                )
            )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
            assert query["detail"] == [JIRA_OAUTH_ACCESS_DENIED_MESSAGE]
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
                consume_connect_state(replay_db, token=state, expected_source=IntegrationSource.jira)
        finally:
            replay_db.close()

    def test_state_issued_for_a_different_provider_is_rejected_by_jira(self, test_user_id):
        """State tokens are bound to a specific provider. A state token
        created for GitHub's connect flow cannot be reused in Jira's
        callback, even though both providers use the same generic routes.
        """
        db = SessionLocal()
        try:
            github_state = _track_state(
                create_connect_state(db, user_id=test_user_id, source=IntegrationSource.github)
            )
        finally:
            db.close()

        db = SessionLocal()
        try:
            with _patch_exchange() as mock_exchange:
                response = asyncio.run(
                    integration_callback(
                        source=IntegrationSource.jira, code="some-code", state=github_state, db=db
                    )
                )

            mock_exchange.assert_not_called()
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.jira,
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

    def test_jira_state_is_rejected_by_a_different_providers_callback(self, test_user_id):
        """The reverse direction: a state token issued for Jira's own connect
        flow must not be accepted by another provider's callback either.
        """
        jira_state = _issue_state(test_user_id, source=IntegrationSource.jira)

        db = SessionLocal()
        try:
            with patch.object(GitHubOAuthProvider, "exchange_code", AsyncMock()) as mock_exchange:
                response = asyncio.run(
                    integration_callback(
                        source=IntegrationSource.github, code="some-code", state=jira_state, db=db
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
        finally:
            db.close()

    def test_missing_code_or_state_redirects_with_error(self):
        db = SessionLocal()
        try:
            response = asyncio.run(integration_callback(source=IntegrationSource.jira, db=db))
            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
        finally:
            db.close()

    def test_failed_jira_exchange_redirects_with_informative_error_and_writes_nothing(self, test_user_id):
        state = _issue_state(test_user_id)

        db = SessionLocal()
        try:
            with _patch_exchange(
                side_effect=JiraOAuthError(
                    "Jira rejected the authorization_code exchange: invalid_grant"
                )
            ):
                response = asyncio.run(
                    integration_callback(source=IntegrationSource.jira, code="bad-code", state=state, db=db)
                )

            query = parse_qs(urlparse(response.headers["location"]).query)
            assert query["status"] == ["error"]
            assert "invalid_grant" in query["detail"][0]

            assert (
                db.query(Integration)
                .filter(
                    Integration.user_id == test_user_id,
                    Integration.source == IntegrationSource.jira,
                )
                .first()
                is None
            )
        finally:
            db.close()


class TestJiraRefreshTokenRotationPersistence:
    """Atlassian rotates the refresh_token on every refresh call (live-confirmed):
    the old one is invalidated immediately and a brand-new one is returned. A
    refresh must therefore persist BOTH the new access_token AND the new
    refresh_token to storage -- persisting only the access_token would leave the
    now-invalid old refresh_token on file and silently break the very next
    refresh. This drives ensure_token_fresh against a real DB row and proves the
    stored refresh_token actually changes to the rotated value.
    """

    def test_refresh_persists_the_new_rotated_refresh_token_to_storage(self, test_user_id):
        # Seed a real integration + token row that's already past expiry (so a
        # refresh is forced) with a known "old" refresh token.
        db = SessionLocal()
        try:
            integration = Integration(
                user_id=test_user_id,
                source=IntegrationSource.jira,
                status=IntegrationStatus.connected,
            )
            db.add(integration)
            db.flush()
            integration_id = integration.id
            db.add(
                OAuthToken(
                    integration_id=integration_id,
                    access_token="jira-old-access-token",
                    refresh_token="jira-OLD-refresh-token",
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                )
            )
            db.commit()
        finally:
            db.close()

        # What's on file *before* the refresh, read back from storage.
        before_db = SessionLocal()
        try:
            before = (
                before_db.query(OAuthToken)
                .filter(OAuthToken.integration_id == integration_id)
                .first()
            )
            old_refresh_in_storage = before.refresh_token
            old_access_in_storage = before.access_token
        finally:
            before_db.close()

        rotated = OAuthTokens(
            access_token="jira-NEW-access-token",
            refresh_token="jira-ROTATED-refresh-token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        db = SessionLocal()
        try:
            with patch.object(
                JiraOAuthProvider, "refresh", AsyncMock(return_value=rotated)
            ) as mock_refresh:
                asyncio.run(ensure_token_fresh(db, IntegrationSource.jira, integration_id=integration_id))
            # The provider was asked to refresh using the OLD token specifically.
            mock_refresh.assert_awaited_once_with("jira-OLD-refresh-token")
        finally:
            db.close()

        # What's on file *after*, read back in a fresh session to prove it was
        # actually committed, not just mutated in the request's session.
        after_db = SessionLocal()
        try:
            after = (
                after_db.query(OAuthToken)
                .filter(OAuthToken.integration_id == integration_id)
                .first()
            )
            new_refresh_in_storage = after.refresh_token
            new_access_in_storage = after.access_token
        finally:
            after_db.close()

        # Before/after, shown explicitly rather than only asserting a pass:
        assert old_refresh_in_storage == "jira-OLD-refresh-token"
        assert old_access_in_storage == "jira-old-access-token"
        assert new_refresh_in_storage == "jira-ROTATED-refresh-token"
        assert new_access_in_storage == "jira-NEW-access-token"
        # The critical property: the stored refresh_token genuinely rotated.
        assert new_refresh_in_storage != old_refresh_in_storage
