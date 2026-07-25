"""Unit tests for the Jira OAuth provider (app/integrations/providers/jira.py): building authorize URLs and
exchanging/refreshing tokens against Atlassian's OAuth endpoints.

HTTP calls to Atlassian are mocked (using unittest.mock.patch), so no real network calls or OAuth app are needed. The
test structure mirrors Slack and GitHub's tests, but the details are Jira-specific: Atlassian expects JSON request
bodies (not form-encoded), returns real HTTP error codes (not always 200), and has refresh tokens that rotate on each
use (unlike GitHub, which doesn't issue refresh tokens at all).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import settings
from app.integrations.constants import JIRA_OAUTH_SCOPES, JIRA_OAUTH_TOKEN_URL
from app.integrations.errors import TokenRefreshError
from app.integrations.providers.jira import JiraOAuthError, JiraOAuthProvider

provider = JiraOAuthProvider()


def _mock_response(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


class TestJiraOAuthErrorHierarchy:
    def test_jira_oauth_error_is_a_token_refresh_error(self):
        """ensure_token_fresh's callers only catch TokenRefreshError -- pin that JiraOAuthError is actually a
        subclass, not just a same-shaped sibling.
        """
        assert issubclass(JiraOAuthError, TokenRefreshError)

    def test_jira_oauth_error_sets_source_and_message_on_the_base_class(self):
        error = JiraOAuthError("something went wrong")

        assert error.source == "jira"
        assert error.message == "something went wrong"
        assert str(error) == "something went wrong"


class TestBuildJiraAuthorizeUrl:
    def test_builds_url_with_expected_scopes_and_state(self):
        url = provider.build_authorize_url("some-state-token")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        assert (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            == "https://auth.atlassian.com/authorize"
        )
        assert query["state"] == ["some-state-token"]
        assert query["client_id"] == [settings.jira_client_id]
        assert query["redirect_uri"] == [settings.jira_redirect_uri]
        assert query["audience"] == ["api.atlassian.com"]
        assert query["response_type"] == ["code"]
        assert query["prompt"] == ["consent"]
        assert query["scope"] == ["read:jira-work read:jira-user offline_access"]

    def test_requests_offline_access_scope_for_refresh_tokens(self):
        """offline_access is what tells Atlassian to actually issue a refresh_token at all -- without it every token
        would be unrefreshable, silently forcing a reconnect every hour.
        """
        url = provider.build_authorize_url("state")
        query = parse_qs(urlparse(url).query)
        assert "offline_access" in query["scope"][0].split(" ")


class TestExchangeCodeForAccessToken:
    def test_success_parses_flat_json_token_response(self):
        response = _mock_response(
            {
                "access_token": "jira-access-token",
                "refresh_token": "jira-refresh-token",
                "expires_in": 3600,
                "scope": "read:jira-work read:jira-user offline_access",
            }
        )
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            tokens = asyncio.run(provider.exchange_code("some-code"))

        assert tokens.access_token == "jira-access-token"
        assert tokens.refresh_token == "jira-refresh-token"
        assert tokens.expires_at is not None

        call_kwargs = mock_post.call_args
        assert call_kwargs.args[0] == JIRA_OAUTH_TOKEN_URL
        assert call_kwargs.kwargs["json"]["grant_type"] == "authorization_code"
        assert call_kwargs.kwargs["json"]["code"] == "some-code"
        assert call_kwargs.kwargs["json"]["redirect_uri"] == settings.jira_redirect_uri

    def test_sends_json_body_not_form_encoded(self):
        """Unlike Slack/GitHub's form-encoded `data=`, Atlassian's token endpoint expects a JSON body -- pin this so a
        copy-paste from the other providers doesn't silently regress to the wrong content type.
        """
        response = _mock_response({"access_token": "tok", "refresh_token": "tok-refresh"})
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            asyncio.run(provider.exchange_code("some-code"))

        assert "json" in mock_post.call_args.kwargs
        assert "data" not in mock_post.call_args.kwargs

    def test_http_error_status_raises_informative_error_not_generic(self):
        """Atlassian returns real HTTP error status codes (unlike Slack/GitHub, which respond HTTP 200 even on
        rejection) -- confirm the error body's error_description is surfaced, not swallowed by raise_for_status.
        """
        response = _mock_response(
            {"error": "invalid_grant", "error_description": "Invalid authorization code"},
            status_code=400,
        )
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("bad-code"))

        assert "Invalid authorization code" in str(exc_info.value)

    def test_missing_access_token_raises_actionable_error(self):
        response = _mock_response({"scope": "read:jira-work"})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "scopes" in str(exc_info.value).lower()

    def test_exchange_without_refresh_token_is_refused(self):
        """We always request offline_access, so the initial exchange must come back with a refresh_token too. A
        response lacking one means the app's Atlassian scopes are misconfigured -- fail loudly at connect time rather
        than storing an unrefreshable connection that only breaks an hour later.
        """
        response = _mock_response({"access_token": "jira-access-token", "expires_in": 3600})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "refresh_token" in str(exc_info.value)
        assert "offline_access" in str(exc_info.value)

    def test_network_failure_raises_informative_error(self):
        with patch(
            "httpx.AsyncClient.post", AsyncMock(side_effect=httpx.ConnectError("boom"))
        ):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "Could not reach Jira" in str(exc_info.value)


class TestRefreshJiraUserToken:
    def test_success_returns_rotated_refresh_token(self):
        """Atlassian rotates refresh tokens on every use -- the response to a refresh call always carries a *new*
        refresh_token that must replace the one just spent.
        """
        response = _mock_response(
            {
                "access_token": "jira-new-access-token",
                "refresh_token": "jira-rotated-refresh-token",
                "expires_in": 3600,
                "scope": "read:jira-work read:jira-user offline_access",
            }
        )
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            tokens = asyncio.run(provider.refresh("jira-old-refresh-token"))

        assert tokens.access_token == "jira-new-access-token"
        assert tokens.refresh_token == "jira-rotated-refresh-token"

        call_kwargs = mock_post.call_args
        assert call_kwargs.args[0] == JIRA_OAUTH_TOKEN_URL
        assert call_kwargs.kwargs["json"]["grant_type"] == "refresh_token"
        assert call_kwargs.kwargs["json"]["refresh_token"] == "jira-old-refresh-token"

    def test_reused_refresh_token_raises_informative_error(self):
        """A refresh token that was already spent (rotation already happened) is rejected by Atlassian with
        invalid_grant -- confirm this surfaces a reconnect-pointing message, not a generic failure.
        """
        response = _mock_response(
            {"error": "invalid_grant", "error_description": "Unknown or invalid refresh token."},
            status_code=403,
        )
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.refresh("already-used-refresh-token"))

        assert "Unknown or invalid refresh token" in str(exc_info.value)
        assert "reconnect" in str(exc_info.value).lower()

    def test_refresh_does_not_send_redirect_uri(self):
        """redirect_uri is only meaningful for the authorization_code grant -- confirm the refresh_token grant body
        doesn't carry a stale one.
        """
        response = _mock_response({"access_token": "tok", "refresh_token": "new-tok"})
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            asyncio.run(provider.refresh("some-refresh-token"))

        assert "redirect_uri" not in mock_post.call_args.kwargs["json"]

    def test_refresh_posts_to_atlassian_token_endpoint_not_slack_or_github(self):
        """The refresh grant must hit Atlassian's *own* token endpoint. Pin the literal URL so a copy-paste from
        slack.py/github.py can't silently point Jira refreshes at the wrong provider's endpoint (which would leak the
        refresh token to another host and always fail).
        """
        response = _mock_response({"access_token": "tok", "refresh_token": "new-tok"})
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            asyncio.run(provider.refresh("some-refresh-token"))

        posted_url = mock_post.call_args.args[0]
        assert posted_url == "https://auth.atlassian.com/oauth/token"
        assert posted_url == JIRA_OAUTH_TOKEN_URL
        assert "slack.com" not in posted_url
        assert "github.com" not in posted_url

    def test_response_without_refresh_token_is_refused_not_silently_stored(self):
        """Atlassian rotates refresh tokens on use, so a refresh response that omits a new refresh_token (shouldn't
        happen given offline_access) must be a hard error -- keeping the just-spent, now-invalid token would silently
        strand the connection with no way to renew again.
        """
        response = _mock_response({"access_token": "jira-new-access-token", "expires_in": 3600})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.refresh("old-refresh-token"))

        assert "refresh_token" in str(exc_info.value)
        assert "offline_access" in str(exc_info.value)


def _malformed_json_response(exc: Exception) -> MagicMock:
    """A 2xx response whose body can't be decoded as JSON (e.g. Atlassian returned HTML or an empty body).
    raise_for_status passes; .json() blows up.
    """
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.side_effect = exc
    response.text = "<html>Bad Gateway</html>"
    return response


class TestMalformedResponseHandling:
    """A 2xx response that isn't the token JSON we expect must raise a clear JiraOAuthError, never an unhandled
    exception -- and it must not be mislabeled as a 'could not reach Jira' network error, since the response *was*
    received.
    """

    def test_non_json_body_on_exchange_raises_malformed_error(self):
        response = _malformed_json_response(ValueError("Expecting value: line 1 column 1 (char 0)"))
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        message = str(exc_info.value)
        assert "could not be parsed" in message
        assert "Could not reach Jira" not in message

    def test_non_json_body_on_refresh_raises_malformed_error(self):
        response = _malformed_json_response(ValueError("Expecting value: line 1 column 1 (char 0)"))
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.refresh("some-refresh-token"))

        assert "could not be parsed" in str(exc_info.value)

    def test_json_that_is_not_an_object_raises_malformed_error(self):
        """A JSON body that decodes to a list/string instead of an object would make `data.get(...)` blow up with
        AttributeError -- confirm it's caught and surfaced as a clean malformed-response error instead.
        """
        response = _mock_response(["not", "an", "object"])
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(JiraOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("some-code"))

        assert "could not be parsed" in str(exc_info.value)
        assert "JSON object" in str(exc_info.value)


class TestJiraCallbackErrorDetail:
    def test_access_denied_maps_to_friendly_message(self):
        detail = provider.callback_error_detail("access_denied")
        assert "cancelled" in detail
        assert "access_denied" not in detail

    def test_unknown_error_code_falls_back_to_generic_message(self):
        detail = provider.callback_error_detail("some_unrecognized_code")
        assert "some_unrecognized_code" not in detail


class TestJiraOAuthScopes:
    def test_scopes_are_exactly_the_expected_classic_read_scopes(self):
        """Non-tautological: assert the literal expected scope strings, not a comparison against JIRA_OAUTH_SCOPES
        itself (which would pass no matter what the constant actually contained).
        """
        assert JIRA_OAUTH_SCOPES == ("read:jira-work", "read:jira-user", "offline_access")

    def test_does_not_request_write_scopes(self):
        assert "write:jira-work" not in JIRA_OAUTH_SCOPES
        assert not any(scope.startswith("manage:") for scope in JIRA_OAUTH_SCOPES)

