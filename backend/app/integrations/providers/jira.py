"""Jira (Atlassian) OAuth provider: builds authorization URLs and exchanges
authorization codes for access tokens. All Jira-specific logic is here (API
endpoints, error response formats, how to parse responses, token refresh) so
the generic connect and token-refresh routes don't need to know about
individual providers.

Atlassian's OAuth flow differs from Slack and GitHub in important ways:

- Request and response format: Atlassian expects a JSON request body (not
  form-encoded like the others), and returns real HTTP error status codes
  (400, 403, etc. with error details in the response body). Slack and GitHub
  always respond HTTP 200 even on rejection, so error details are in the body.
- Refresh token rotation: Atlassian requires "offline_access" scope to issue
  refresh tokens at all. Once you have a refresh token, it rotates on every
  use — when you refresh, Atlassian gives you a new refresh token and
  invalidates the old one immediately. Unused tokens expire after ~90 days.
- Token response shape: Both the initial authorization and refresh flows
  return the same flat JSON structure, so we parse both with one function.
- Cloud ID discovery (NOT done here): After getting a token, you can't call
  Jira's API until you discover the user's cloud ID via a separate API call
  (`GET /oauth/token/accessible-resources`). That discovery step is outside
  this module's scope — this module only handles obtaining and refreshing
  tokens. The actual Jira API integration lives elsewhere (currently the Jira
  MCP server in toolbelt.py uses separate shared credentials untouched by
  this module).
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.integrations.constants import (
    JIRA_CALLBACK_MISSING_PARAMS_MESSAGE, JIRA_MALFORMED_RESPONSE_MESSAGE, JIRA_MISSING_ACCESS_TOKEN_MESSAGE,
    JIRA_OAUTH_AUTHORIZE_URL, JIRA_OAUTH_CALLBACK_ERROR_MESSAGES, JIRA_OAUTH_NETWORK_ERROR_MESSAGE, JIRA_OAUTH_SCOPES,
    JIRA_OAUTH_TOKEN_URL, JIRA_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE, JIRA_RESPONSE_MISSING_REFRESH_TOKEN_MESSAGE,
    JIRA_TOKEN_EXCHANGE_FAILED_MESSAGE, JIRA_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE, JIRA_TOKEN_NOT_FOUND_MESSAGE,
    JIRA_TOKEN_REFRESH_FAILED_MESSAGE, JIRA_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE,
)
from app.integrations.errors import TokenRefreshError
from app.integrations.models import IntegrationSource
from app.integrations.providers.base import OAuthProvider, OAuthTokens


class JiraOAuthError(TokenRefreshError):
    """Raised when Jira/Atlassian rejects an OAuth request or the request
    can't be sent."""

    def __init__(self, message: str) -> None:
        super().__init__(source=IntegrationSource.jira.value, message=message)


def _compute_expires_at(expires_in: int | None) -> datetime | None:
    if expires_in is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _parse_token_response(data: dict, *, require_refresh_token: bool) -> OAuthTokens:
    """Extract access token, refresh token, and expiry from Atlassian's
    response. Used by both the initial code exchange and token refresh flows,
    since both return the same structure.

    Because we always request `offline_access`, Atlassian is expected to return
    a refresh_token on both flows, and because those refresh tokens rotate on
    every use, a missing one is a hard error (`require_refresh_token=True`),
    never silently accepted: storing `None` would strand the connection with no
    way to renew it (the just-spent token Atlassian rotated away is already
    invalid). See JIRA_RESPONSE_MISSING_REFRESH_TOKEN_MESSAGE.
    """
    access_token = data.get("access_token")
    if not access_token:
        raise JiraOAuthError(JIRA_MISSING_ACCESS_TOKEN_MESSAGE)

    refresh_token = data.get("refresh_token")
    if require_refresh_token and not refresh_token:
        raise JiraOAuthError(JIRA_RESPONSE_MISSING_REFRESH_TOKEN_MESSAGE)

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=_compute_expires_at(data.get("expires_in")),
        scope=data.get("scope", ""),
    )


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text or "unknown_error"
    if not isinstance(data, dict):
        return "unknown_error"
    return data.get("error_description") or data.get("error", "unknown_error")


def _parse_httpx_response(
    response: httpx.Response, *, failed_message: str, require_refresh_token: bool
) -> OAuthTokens:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise JiraOAuthError(failed_message.format(jira_error=_extract_error_detail(response))) from exc

    # A 2xx with a body that isn't the token JSON we expect (non-JSON, or JSON
    # that isn't an object) is a malformed *received* response, not a transport
    # failure -- surface it as such rather than as a "could not reach Jira"
    # network error, which would be misleading.
    try:
        data = response.json()
    except ValueError as exc:
        raise JiraOAuthError(JIRA_MALFORMED_RESPONSE_MESSAGE.format(detail=str(exc))) from exc

    if not isinstance(data, dict):
        raise JiraOAuthError(
            JIRA_MALFORMED_RESPONSE_MESSAGE.format(
                detail=f"expected a JSON object, got {type(data).__name__}"
            )
        )

    return _parse_token_response(data, require_refresh_token=require_refresh_token)


class JiraOAuthProvider(OAuthProvider):
    """Jira's implementation of the shared OAuthProvider interface.

    The generic routes for connecting and refreshing tokens call ONLY this
    class and the helper functions above. This ensures Jira-specific logic
    (the correct endpoints, how to parse responses, error handling) lives in
    one place and doesn't leak into shared route code.
    """

    source = IntegrationSource.jira
    error_type = JiraOAuthError

    token_not_found_message = JIRA_TOKEN_NOT_FOUND_MESSAGE
    missing_refresh_token_message = JIRA_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE
    persist_failed_message = JIRA_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE
    missing_params_message = JIRA_CALLBACK_MISSING_PARAMS_MESSAGE

    def build_authorize_url(self, state: str) -> str:
        params = {
            "audience": "api.atlassian.com",
            "client_id": settings.jira_client_id,
            "scope": " ".join(JIRA_OAUTH_SCOPES),
            "redirect_uri": settings.jira_redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        return f"{JIRA_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    JIRA_OAUTH_TOKEN_URL,
                    json={
                        "grant_type": "authorization_code",
                        "client_id": settings.jira_client_id,
                        "client_secret": settings.jira_client_secret,
                        "code": code,
                        "redirect_uri": settings.jira_redirect_uri,
                    },
                )
            except httpx.HTTPError as exc:
                raise JiraOAuthError(JIRA_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))) from exc

        return _parse_httpx_response(
            response, failed_message=JIRA_TOKEN_EXCHANGE_FAILED_MESSAGE, require_refresh_token=True
        )

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    JIRA_OAUTH_TOKEN_URL,
                    json={
                        "grant_type": "refresh_token",
                        "client_id": settings.jira_client_id,
                        "client_secret": settings.jira_client_secret,
                        "refresh_token": refresh_token,
                    },
                )
            except httpx.HTTPError as exc:
                raise JiraOAuthError(JIRA_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))) from exc

        return _parse_httpx_response(
            response, failed_message=JIRA_TOKEN_REFRESH_FAILED_MESSAGE, require_refresh_token=True
        )

    def callback_error_detail(self, error_code: str) -> str:
        return JIRA_OAUTH_CALLBACK_ERROR_MESSAGES.get(error_code, JIRA_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE)
