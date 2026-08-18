"""Unit tests for the Calendar OAuth provider (app/integrations/providers/calendar.py): building authorize URLs and
exchanging/refreshing tokens against Google's OAuth endpoints.

HTTP calls to Google are mocked (using unittest.mock.patch), so no real network calls or OAuth client are needed. The
test structure mirrors Jira's tests, since Google shares Atlassian's shape of returning real HTTP error codes with a
JSON error body. The Google-specific parts are that refresh responses legitimately omit refresh_token (Google reuses
the original rather than rotating it) and that the requested scope must stay read-only.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import settings
from app.integrations.errors import TokenRefreshError
from app.integrations.providers.calendar import (
    CALENDAR_OAUTH_SCOPES, CALENDAR_OAUTH_TOKEN_URL, CalendarOAuthError, CalendarOAuthProvider,
)

provider = CalendarOAuthProvider()


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


class TestCalendarOAuthErrorHierarchy:
    def test_calendar_oauth_error_is_a_token_refresh_error(self):
        """ensure_token_fresh's callers only catch TokenRefreshError -- pin that CalendarOAuthError is actually a
        subclass, not just a same-shaped sibling.
        """
        assert issubclass(CalendarOAuthError, TokenRefreshError)

    def test_calendar_oauth_error_sets_source_and_message_on_the_base_class(self):
        error = CalendarOAuthError("something went wrong")

        assert error.source == "calendar"
        assert error.message == "something went wrong"
        assert str(error) == "something went wrong"


class TestBuildCalendarAuthorizeUrl:
    def test_builds_url_with_expected_scopes_and_state(self):
        url = provider.build_authorize_url("some-state-token")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        assert (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            == "https://accounts.google.com/o/oauth2/v2/auth"
        )
        assert query["state"] == ["some-state-token"]
        assert query["client_id"] == [settings.google_client_id]
        assert query["redirect_uri"] == [settings.calendar_redirect_uri]
        assert query["response_type"] == ["code"]
        assert query["scope"] == ["https://www.googleapis.com/auth/calendar.readonly"]

    def test_requests_offline_access_and_consent_for_a_refresh_token(self):
        """Google only issues a refresh_token when access_type=offline is paired with an actual consent prompt --
        without both, a returning user's connection dies in an hour with no way to renew it.
        """
        query = parse_qs(urlparse(provider.build_authorize_url("state")).query)

        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]

    def test_requests_read_only_scope_and_nothing_writable(self):
        """This app never writes calendar events. A write scope reaching the consent screen would grant standing
        access no code path here needs, so pin the exact scope set rather than only checking readonly is present.
        """
        assert CALENDAR_OAUTH_SCOPES == ("https://www.googleapis.com/auth/calendar.readonly",)

        granted = parse_qs(urlparse(provider.build_authorize_url("state")).query)["scope"][0].split(" ")

        assert granted == ["https://www.googleapis.com/auth/calendar.readonly"]
        assert not any(scope.endswith("/auth/calendar") for scope in granted)
        assert not any("events" in scope for scope in granted)

    def test_uses_the_integration_callback_not_the_sign_in_callback(self):
        """Calendar shares Google's OAuth client with sign-in but must land on its own callback; sending the connect
        flow to /auth/google/callback would run an integration code through the sign-in handler.
        """
        query = parse_qs(urlparse(provider.build_authorize_url("state")).query)

        assert query["redirect_uri"] != [settings.google_redirect_uri]
        assert query["redirect_uri"][0].endswith("/integrations/calendar/callback")


class TestExchangeCodeForAccessToken:
    def test_success_parses_flat_json_token_response(self):
        response = _mock_response(
            {
                "access_token": "google-access-token",
                "refresh_token": "google-refresh-token",
                "expires_in": 3599,
                "scope": "https://www.googleapis.com/auth/calendar.readonly",
            }
        )
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            tokens = asyncio.run(provider.exchange_code("auth-code"))

        assert tokens.access_token == "google-access-token"
        assert tokens.refresh_token == "google-refresh-token"
        assert tokens.expires_at is not None

    def test_posts_form_encoded_body_to_googles_token_endpoint(self):
        """Google's token endpoint takes form-encoded parameters, unlike Atlassian's JSON body -- a JSON post here
        is rejected with invalid_request.
        """
        response = _mock_response(
            {"access_token": "t", "refresh_token": "r", "expires_in": 3599}
        )
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            asyncio.run(provider.exchange_code("auth-code"))

        _, kwargs = mock_post.call_args
        assert mock_post.call_args[0][0] == CALENDAR_OAUTH_TOKEN_URL
        assert "json" not in kwargs
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert kwargs["data"]["code"] == "auth-code"
        assert kwargs["data"]["redirect_uri"] == settings.calendar_redirect_uri

    def test_missing_refresh_token_on_exchange_is_refused(self):
        """A connect that yields no refresh_token would stop working within the hour, so it fails loudly at connect
        time instead of being stored as a silently doomed connection.
        """
        response = _mock_response({"access_token": "t", "expires_in": 3599})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(CalendarOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("auth-code"))

        assert "refresh_token" in str(exc_info.value)

    def test_missing_access_token_raises(self):
        response = _mock_response({"refresh_token": "r"})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(CalendarOAuthError):
                asyncio.run(provider.exchange_code("auth-code"))

    def test_http_error_status_surfaces_googles_error_description(self):
        response = _mock_response(
            {"error": "invalid_grant", "error_description": "Bad Request"}, status_code=400
        )
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(CalendarOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("auth-code"))

        assert "Bad Request" in str(exc_info.value)

    def test_network_failure_raises_calendar_oauth_error(self):
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=httpx.ConnectError("boom"))):
            with pytest.raises(CalendarOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("auth-code"))

        assert "Could not reach Google" in str(exc_info.value)

    def test_non_json_success_body_is_reported_as_malformed_not_unreachable(self):
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("no json")
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(CalendarOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("auth-code"))

        assert "could not be parsed" in str(exc_info.value)
        assert "Could not reach Google" not in str(exc_info.value)


class TestRefreshAccessToken:
    def test_refresh_succeeds_without_a_new_refresh_token(self):
        """Google reuses the original refresh token rather than rotating it, so a refresh response with no
        refresh_token is normal and must not be treated as an error.
        """
        response = _mock_response({"access_token": "new-access-token", "expires_in": 3599})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            tokens = asyncio.run(provider.refresh("stored-refresh-token"))

        assert tokens.access_token == "new-access-token"
        assert tokens.refresh_token is None

    def test_refresh_posts_the_stored_refresh_token(self):
        response = _mock_response({"access_token": "new-access-token", "expires_in": 3599})
        mock_post = AsyncMock(return_value=response)
        with patch("httpx.AsyncClient.post", mock_post):
            asyncio.run(provider.refresh("stored-refresh-token"))

        kwargs = mock_post.call_args[1]
        assert kwargs["data"]["grant_type"] == "refresh_token"
        assert kwargs["data"]["refresh_token"] == "stored-refresh-token"

    def test_revoked_refresh_token_raises_with_reconnect_guidance(self):
        response = _mock_response(
            {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
            status_code=400,
        )
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(CalendarOAuthError) as exc_info:
                asyncio.run(provider.refresh("stale-refresh-token"))

        assert "reconnect Calendar" in str(exc_info.value)


class TestErrorMessagesDoNotLeakCredentials:
    def test_error_detail_does_not_echo_a_non_json_body(self):
        """Google's token endpoint answers errors in JSON. An unparseable error body is echoed as a fixed string
        rather than reflected verbatim, so a body that happened to contain token material can't reach the message.
        """
        response = MagicMock()
        response.status_code = 400
        response.text = "ya29.a0-SECRET-ACCESS-TOKEN-VALUE"
        response.json.side_effect = ValueError("no json")
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(CalendarOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("auth-code"))

        assert "SECRET" not in str(exc_info.value)
        assert "unknown_error" in str(exc_info.value)

    def test_exchange_failure_message_does_not_contain_the_client_secret(self):
        response = _mock_response({"error": "invalid_client"}, status_code=401)
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=response)):
            with pytest.raises(CalendarOAuthError) as exc_info:
                asyncio.run(provider.exchange_code("auth-code"))

        assert settings.google_client_secret not in str(exc_info.value)


class TestCallbackErrorDetail:
    def test_access_denied_maps_to_cancelled_message(self):
        assert "cancelled" in provider.callback_error_detail("access_denied")

    def test_unknown_error_code_maps_to_generic_message(self):
        detail = provider.callback_error_detail("some_unrecognized_google_code")

        assert "reported an error" in detail
        assert "some_unrecognized_google_code" not in detail
