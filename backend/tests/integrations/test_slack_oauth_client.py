"""Unit tests for app/integrations/providers/slack.py: the SlackOAuthProvider's
authorize-URL builder and code-exchange/refresh HTTP calls to Slack.
httpx.AsyncClient.post is monkeypatched -- no real network calls, no real Slack
workspace involved. These pin that the provider methods carry Slack's exact
wire logic (correct endpoint, error normalization) after the generic-interface
refactor.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.integrations.errors import TokenRefreshError
from app.integrations.providers.slack import (
    SLACK_OAUTH_ACCESS_URL, SLACK_OAUTH_USER_SCOPES, SlackOAuthError, SlackOAuthProvider,
)

provider = SlackOAuthProvider()


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


class TestSlackOAuthErrorHierarchy:
    def test_slack_oauth_error_is_a_token_refresh_error(self):
        """ensure_token_fresh's callers only catch TokenRefreshError -- pin
        that SlackOAuthError is actually a subclass, not just a same-shaped
        sibling."""
        assert issubclass(SlackOAuthError, TokenRefreshError)

    def test_slack_oauth_error_sets_source_and_message_on_the_base_class(self):
        """TokenRefreshError requires both `source` and `message` -- pin
        that SlackOAuthError actually supplies both to the base __init__
        rather than only satisfying `message` and leaving `source` unset."""
        error = SlackOAuthError("something went wrong")

        assert error.source == "slack"
        assert error.message == "something went wrong"
        assert str(error) == "something went wrong"


class TestBuildSlackAuthorizeUrl:
    def test_builds_url_with_expected_scopes_and_state(self):
        url = provider.build_authorize_url("some-state-token")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        assert (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            == "https://slack.com/oauth/v2/authorize"
        )
        assert query["state"] == ["some-state-token"]
        assert query["client_id"] == [settings.slack_client_id]
        assert query["redirect_uri"] == [settings.slack_redirect_uri]
        assert query["user_scope"] == [",".join(SLACK_OAUTH_USER_SCOPES)]

    def test_does_not_request_im_history(self):
        url = provider.build_authorize_url("state")
        query = parse_qs(urlparse(url).query)
        assert "im:history" not in query["user_scope"][0].split(",")


class TestExchangeCodeForUserToken:
    def test_success_parses_authed_user_token(self):
        response = _mock_response(
            {
                "ok": True,
                "authed_user": {
                    "id": "U123",
                    "access_token": "xoxp-user-token",
                    "refresh_token": "xoxe-refresh-token",
                    "expires_in": 43200,
                    "scope": "channels:read,channels:history",
                },
            }
        )
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            tokens = asyncio.run(provider.exchange_code("some-code"))

        assert tokens.access_token == "xoxp-user-token"
        assert tokens.refresh_token == "xoxe-refresh-token"
        assert tokens.authed_user_id == "U123"
        assert tokens.expires_at is not None

        call_kwargs = mock_post.call_args
        assert call_kwargs.args[0] == SLACK_OAUTH_ACCESS_URL
        assert call_kwargs.kwargs["data"]["code"] == "some-code"
        assert call_kwargs.kwargs["data"]["redirect_uri"] == settings.slack_redirect_uri

    def test_slack_error_raises_informative_error_not_generic(self):
        response = _mock_response({"ok": False, "error": "invalid_code"})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(SlackOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("bad-code"))

        assert "invalid_code" in str(exc_info.value)
        assert "oauth.v2.access" in str(exc_info.value)

    def test_missing_authed_user_token_raises_actionable_error(self):
        """When Slack responds with ok=True but no user token, the error should
        tell the user to configure the Slack app with the required scopes,
        not crash with a KeyError.
        """
        response = _mock_response({"ok": True, "authed_user": {}})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(SlackOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "User Token Scopes" in str(exc_info.value)

    def test_network_failure_raises_informative_error(self):
        import httpx

        with patch(
            "httpx.AsyncClient.post", AsyncMock(side_effect=httpx.ConnectError("boom"))
        ):
            with pytest.raises(SlackOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "Could not reach Slack" in str(exc_info.value)


class TestRefreshSlackUserToken:
    def test_success_parses_flat_response(self):
        response = _mock_response(
            {
                "ok": True,
                "access_token": "xoxp-new-token",
                "refresh_token": "xoxe-new-refresh",
                "expires_in": 43200,
                "user_id": "U123",
                "scope": "channels:read",
            }
        )
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            tokens = asyncio.run(provider.refresh("xoxe-old-refresh"))

        assert tokens.access_token == "xoxp-new-token"
        assert tokens.refresh_token == "xoxe-new-refresh"
        assert tokens.authed_user_id == "U123"

        call_kwargs = mock_post.call_args
        assert call_kwargs.args[0] == SLACK_OAUTH_ACCESS_URL
        assert call_kwargs.kwargs["data"]["refresh_token"] == "xoxe-old-refresh"

    def test_slack_error_raises_informative_error(self):
        response = _mock_response({"ok": False, "error": "invalid_refresh_token"})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(SlackOAuthError) as exc_info:
                asyncio.run(provider.refresh("revoked-token"))

        assert "invalid_refresh_token" in str(exc_info.value)
        assert "reconnect" in str(exc_info.value).lower()

    def test_refresh_posts_to_oauth_v2_access_not_oauth_v2_exchange(self):
        """Verifies that token refresh uses the oauth.v2.access endpoint with
        grant_type=refresh_token (not a different endpoint). This was a real
        bug found during testing, so we pin it explicitly.
        """
        response = _mock_response({"ok": True, "access_token": "xoxp-new", "user_id": "U1"})
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            asyncio.run(provider.refresh("xoxe-old-refresh"))

        assert mock_post.call_args.args[0] == SLACK_OAUTH_ACCESS_URL
        assert mock_post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
