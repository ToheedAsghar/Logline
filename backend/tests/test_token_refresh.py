"""Tests for the token refresh module.

Tests the ensure_token_fresh function, which checks if a stored OAuth token is expiring and refreshes it if needed.
The database is mocked to avoid hitting the real test DB; Slack's API is also mocked so no real network calls are
made. These tests verify the refresh logic: when to refresh, how to handle missing tokens, and error cases.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.constants import OAUTH_TOKEN_REFRESH_MARGIN_SECONDS
from app.integrations.models import IntegrationSource
from app.integrations.providers.base import OAuthTokens
from app.integrations.providers.slack import SlackOAuthError, SlackOAuthProvider
from app.integrations.token_refresh import ensure_token_fresh


def _fake_db_with_token(token) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = token
    return db


def _token(*, expires_at, refresh_token="xoxe-refresh", access_token="xoxp-old"):
    token = MagicMock()
    token.expires_at = expires_at
    token.refresh_token = refresh_token
    token.access_token = access_token
    return token


class TestEnsureTokenFreshUnimplementedSource:
    def test_source_with_no_registered_refresher_raises_not_implemented(self):
        db = MagicMock()

        with pytest.raises(NotImplementedError) as exc_info:
            asyncio.run(ensure_token_fresh(db, IntegrationSource.calendar, integration_id=1))

        assert "calendar" in str(exc_info.value)


class TestEnsureTokenFreshSkipsWhenNotNearExpiry:
    def test_far_future_expiry_does_not_call_refresh(self):
        token = _token(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        db = _fake_db_with_token(token)

        with patch.object(
            SlackOAuthProvider, "refresh", AsyncMock()
        ) as mock_refresh:
            result = asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=1))

        mock_refresh.assert_not_called()
        assert result is token
        db.commit.assert_not_called()

    def test_no_expiry_set_treated_as_never_expiring(self):
        token = _token(expires_at=None)
        db = _fake_db_with_token(token)

        with patch.object(
            SlackOAuthProvider, "refresh", AsyncMock()
        ) as mock_refresh:
            result = asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=1))

        mock_refresh.assert_not_called()
        assert result is token


class TestEnsureTokenFreshRefreshesWhenNeeded:
    def test_within_refresh_margin_calls_refresh_and_updates_row(self):
        token = _token(
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=OAUTH_TOKEN_REFRESH_MARGIN_SECONDS - 10)
        )
        db = _fake_db_with_token(token)
        new_tokens = OAuthTokens(
            access_token="xoxp-new",
            refresh_token="xoxe-new-refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
        )

        with patch.object(
            SlackOAuthProvider, "refresh", AsyncMock(return_value=new_tokens),
        ) as mock_refresh:
            result = asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=1))

        mock_refresh.assert_called_once_with("xoxe-refresh")
        assert result.access_token == "xoxp-new"
        assert result.refresh_token == "xoxe-new-refresh"
        db.query.return_value.filter.return_value.with_for_update.assert_called_once()
        db.commit.assert_called_once()

    def test_already_expired_also_triggers_refresh(self):
        token = _token(expires_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        db = _fake_db_with_token(token)
        new_tokens = OAuthTokens(access_token="xoxp-new", expires_at=None)

        with patch.object(
            SlackOAuthProvider, "refresh", AsyncMock(return_value=new_tokens),
        ) as mock_refresh:
            asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=1))

        mock_refresh.assert_called_once()

    def test_refresh_response_without_new_refresh_token_keeps_old_one(self):
        """When Slack refreshes a token but doesn't rotate the refresh_token itself, we must keep the old one. Clearing
        it would break future refreshes.
        """
        token = _token(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        db = _fake_db_with_token(token)
        new_tokens = OAuthTokens(
            access_token="xoxp-new", refresh_token=None, expires_at=None
        )

        with patch.object(
            SlackOAuthProvider, "refresh", AsyncMock(return_value=new_tokens),
        ):
            result = asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=1))

        assert result.refresh_token == "xoxe-refresh"


class TestEnsureTokenFreshErrors:
    def test_no_token_on_file_raises_informative_error(self):
        db = _fake_db_with_token(None)

        with pytest.raises(SlackOAuthError) as exc_info:
            asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=999))

        assert "999" in str(exc_info.value)
        assert "connect" in str(exc_info.value).lower()

    def test_near_expiry_without_refresh_token_raises_informative_error(self):
        token = _token(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            refresh_token=None,
        )
        db = _fake_db_with_token(token)

        with patch.object(
            SlackOAuthProvider, "refresh", AsyncMock()
        ) as mock_refresh:
            with pytest.raises(SlackOAuthError) as exc_info:
                asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=5))

        mock_refresh.assert_not_called()
        assert "reconnect" in str(exc_info.value).lower()

    def test_slack_refresh_failure_propagates_informative_error(self):
        token = _token(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        db = _fake_db_with_token(token)

        with patch.object(
            SlackOAuthProvider, "refresh", AsyncMock(
                side_effect=SlackOAuthError(
                    "Slack rejected the oauth.v2.access refresh request: invalid_refresh_token"
                )
            ),
        ):
            with pytest.raises(SlackOAuthError) as exc_info:
                asyncio.run(ensure_token_fresh(db, IntegrationSource.slack, integration_id=5))

        assert "invalid_refresh_token" in str(exc_info.value)
        db.commit.assert_not_called()

