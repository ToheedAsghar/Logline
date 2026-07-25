"""Unit tests for the GitHub OAuth provider (app/integrations/providers/github.py): building authorize URLs and
exchanging authorization codes for access tokens.

These tests mock the HTTP calls to GitHub (using unittest.mock.patch) so there are no real network calls and no real
GitHub OAuth App is needed. The test structure and coverage mirrors test_slack_oauth_client.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.integrations.constants import GITHUB_OAUTH_ACCESS_TOKEN_URL
from app.integrations.errors import TokenRefreshError
from app.integrations.providers.github import GitHubOAuthError, GitHubOAuthProvider

provider = GitHubOAuthProvider()


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


class TestGitHubOAuthErrorHierarchy:
    def test_github_oauth_error_is_a_token_refresh_error(self):
        """ensure_token_fresh's callers only catch TokenRefreshError -- pin that GitHubOAuthError is actually a
        subclass, not just a same-shaped sibling.
        """
        assert issubclass(GitHubOAuthError, TokenRefreshError)

    def test_github_oauth_error_sets_source_and_message_on_the_base_class(self):
        error = GitHubOAuthError("something went wrong")

        assert error.source == "github"
        assert error.message == "something went wrong"
        assert str(error) == "something went wrong"


class TestBuildGitHubAuthorizeUrl:
    def test_builds_url_with_expected_scopes_and_state(self):
        url = provider.build_authorize_url("some-state-token")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        assert (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            == "https://github.com/login/oauth/authorize"
        )
        assert query["state"] == ["some-state-token"]
        assert query["client_id"] == [settings.github_client_id]
        assert query["redirect_uri"] == [settings.github_redirect_uri]
        assert query["scope"] == ["repo"]


class TestExchangeCodeForAccessToken:
    def test_success_parses_access_token(self):
        response = _mock_response(
            {
                "access_token": "gho_user-token",
                "scope": "repo",
                "token_type": "bearer",
            }
        )
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            tokens = asyncio.run(provider.exchange_code("some-code"))

        assert tokens.access_token == "gho_user-token"
        assert tokens.scope == "repo"
        assert tokens.refresh_token is None
        assert tokens.expires_at is None

        call_kwargs = mock_post.call_args
        assert call_kwargs.args[0] == GITHUB_OAUTH_ACCESS_TOKEN_URL
        assert call_kwargs.kwargs["data"]["code"] == "some-code"
        assert call_kwargs.kwargs["data"]["redirect_uri"] == settings.github_redirect_uri
        assert call_kwargs.kwargs["headers"] == {"Accept": "application/json"}

    def test_github_error_raises_informative_error_not_generic(self):
        """GitHub returns HTTP 200 even on rejection -- the error is an `error` field in the JSON body, not an HTTP
        status code.
        """
        response = _mock_response(
            {
                "error": "bad_verification_code",
                "error_description": "The code passed is incorrect or expired.",
            }
        )
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(GitHubOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("bad-code"))

        assert "code passed is incorrect or expired" in str(exc_info.value)

    def test_missing_access_token_raises_actionable_error(self):
        response = _mock_response({})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(GitHubOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "scopes" in str(exc_info.value).lower()

    def test_network_failure_raises_informative_error(self):
        import httpx

        with patch(
            "httpx.AsyncClient.post", AsyncMock(side_effect=httpx.ConnectError("boom"))
        ):
            with pytest.raises(GitHubOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "Could not reach GitHub" in str(exc_info.value)


class TestRefreshGitHubUserToken:
    def test_refresh_raises_without_making_a_network_call(self):
        """GitHub OAuth Apps don't issue refresh tokens or expiring access tokens -- refresh() is a documented no-op that
        raises rather than silently succeeding or hitting a nonexistent endpoint.
        """
        with patch("httpx.AsyncClient.post", AsyncMock()) as mock_post:
            with pytest.raises(GitHubOAuthError) as exc_info:
                asyncio.run(provider.refresh("irrelevant-token"))

        mock_post.assert_not_called()
        assert "don't support refreshing" in str(exc_info.value) or "refresh" in str(exc_info.value).lower()


class TestGitHubCallbackErrorDetail:
    def test_access_denied_maps_to_friendly_message(self):
        detail = provider.callback_error_detail("access_denied")
        assert "cancelled" in detail
        assert "access_denied" not in detail

    def test_unknown_error_code_falls_back_to_generic_message(self):
        detail = provider.callback_error_detail("some_unrecognized_code")
        assert "some_unrecognized_code" not in detail

