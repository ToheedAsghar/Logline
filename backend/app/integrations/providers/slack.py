"""Slack OAuth provider: builds authorization URLs and exchanges authorization codes for access tokens. All
Slack-specific logic is here (API endpoints, error response formats, how to parse responses, token refresh) so the
generic connect and token-refresh routes don't need to know about individual providers.

This pattern (a dedicated provider class per service) will scale to future integrations like Jira or Calendar -- each
gets one subclass here and one entry in the provider registry, with no changes to the shared route logic.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.integrations.errors import TokenRefreshError
from app.integrations.models import IntegrationSource
from app.integrations.providers.base import OAuthProvider, OAuthTokens

SLACK_OAUTH_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_ACCESS_URL = "https://slack.com/api/oauth.v2.access"

SLACK_OAUTH_USER_SCOPES = (
    "channels:read",
    "channels:history",
    "groups:history",
    "im:read",
)

SLACK_CONNECT_STATE_PURPOSE = "slack_connect"

SLACK_TOKEN_EXCHANGE_FAILED_MESSAGE = (
    "Slack rejected the {context} request: {slack_error}. This usually means the "
    "authorization code already expired or was already used. Restart the connect "
    "flow from the Integrations page."
)

SLACK_TOKEN_REFRESH_FAILED_MESSAGE = (
    "Slack rejected the oauth.v2.access refresh request: {slack_error}. The stored "
    "refresh token may have been revoked (e.g. the user removed the app in Slack) -- "
    "reconnect Slack from the Integrations page."
)

SLACK_OAUTH_NETWORK_ERROR_MESSAGE = (
    "Could not reach Slack to complete the OAuth request: {detail}. Check network "
    "connectivity and try again."
)

SLACK_MISSING_USER_TOKEN_MESSAGE = (
    "Slack's response did not include a user access token. This app's Slack "
    "configuration is likely missing the required User Token Scopes ({scopes}) under "
    "OAuth & Permissions -- add them there before retrying the connect flow."
).format(scopes=", ".join(SLACK_OAUTH_USER_SCOPES))

SLACK_TOKEN_NOT_FOUND_MESSAGE = (
    "No stored Slack OAuth token was found for integration_id={integration_id}. The "
    "user needs to connect Slack from the Integrations page before this token can be "
    "refreshed."
)

SLACK_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE = (
    "The stored Slack token for integration_id={integration_id} is near/past expiry "
    "but has no refresh_token on file, so it can't be silently refreshed. The user "
    "needs to reconnect Slack from the Integrations page."
)

SLACK_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE = (
    "Could not persist the refreshed Slack token pair for integration_id={integration_id} "
    "after Slack rotated the credentials. Reconnect Slack from the Integrations page."
)

SLACK_CALLBACK_MISSING_PARAMS_MESSAGE = (
    "Slack's callback did not include both `code` and `state` -- the connect flow "
    "did not complete. Restart it from the Integrations page."
)

SLACK_OAUTH_ACCESS_DENIED_MESSAGE = (
    "Slack authorization was not granted -- the connect flow was cancelled. Restart "
    "it from the Integrations page if you'd like to connect Slack."
)

SLACK_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE = (
    "Slack's callback reported an error completing the connect flow. Restart it "
    "from the Integrations page."
)

SLACK_OAUTH_CALLBACK_ERROR_MESSAGES = {
    "access_denied": SLACK_OAUTH_ACCESS_DENIED_MESSAGE,
}


class SlackOAuthError(TokenRefreshError):
    """Raised when Slack rejects an OAuth request or the request can't be sent."""

    def __init__(self, message: str) -> None:
        super().__init__(source=IntegrationSource.slack.value, message=message)


def _compute_expires_at(expires_in: int | None) -> datetime | None:
    if expires_in is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _parse_authed_user_response(data: dict) -> OAuthTokens:
    """Parse Slack's response after exchanging an authorization code for a user token during the initial OAuth flow.

    Slack's response structure differs based on what permissions were requested: for user tokens only (no bot
    permissions), the token is in an `authed_user` field. If bot permissions were also granted, a top-level
    `access_token` would appear instead.
    """
    if not data.get("ok"):
        raise SlackOAuthError(
            SLACK_TOKEN_EXCHANGE_FAILED_MESSAGE.format(
                context="oauth.v2.access",
                slack_error=data.get("error", "unknown_error"),
            )
        )

    authed_user = data.get("authed_user") or {}
    access_token = authed_user.get("access_token")
    if not access_token:
        raise SlackOAuthError(SLACK_MISSING_USER_TOKEN_MESSAGE)

    return OAuthTokens(
        access_token=access_token,
        refresh_token=authed_user.get("refresh_token"),
        expires_at=_compute_expires_at(authed_user.get("expires_in")),
        scope=authed_user.get("scope", ""),
        authed_user_id=authed_user.get("id", ""),
    )


def _parse_refresh_response(data: dict) -> OAuthTokens:
    """Parse the flat refresh response returned by oauth.v2.access."""
    if not data.get("ok"):
        raise SlackOAuthError(
            SLACK_TOKEN_REFRESH_FAILED_MESSAGE.format(
                slack_error=data.get("error", "unknown_error")
            )
        )

    access_token = data.get("access_token")
    if not access_token:
        raise SlackOAuthError(SLACK_MISSING_USER_TOKEN_MESSAGE)

    return OAuthTokens(
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        expires_at=_compute_expires_at(data.get("expires_in")),
        scope=data.get("scope", ""),
        authed_user_id=data.get("authed_user_id")
        or data.get("user_id", "")
        or (data.get("authed_user") or {}).get("id", ""),
    )


def _parse_httpx_response(response: httpx.Response, parser) -> OAuthTokens:
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SlackOAuthError(
            SLACK_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise SlackOAuthError(
            SLACK_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))
        ) from exc

    return parser(data)


class SlackOAuthProvider(OAuthProvider):
    """Slack's implementation of the shared OAuthProvider interface.

    The generic routes for connecting and refreshing tokens call ONLY this class and the helper functions above. This
    ensures Slack-specific logic (the correct endpoints, how to parse responses, error handling) lives in one place
    and doesn't leak into shared route code.
    """

    source = IntegrationSource.slack
    error_type = SlackOAuthError

    token_not_found_message = SLACK_TOKEN_NOT_FOUND_MESSAGE
    missing_refresh_token_message = SLACK_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE
    persist_failed_message = SLACK_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE
    missing_params_message = SLACK_CALLBACK_MISSING_PARAMS_MESSAGE

    def build_authorize_url(self, state: str) -> str:
        params = {
            "client_id": settings.slack_client_id,
            "user_scope": ",".join(SLACK_OAUTH_USER_SCOPES),
            "redirect_uri": settings.slack_redirect_uri,
            "state": state,
        }
        return f"{SLACK_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    SLACK_OAUTH_ACCESS_URL,
                    data={
                        "client_id": settings.slack_client_id,
                        "client_secret": settings.slack_client_secret,
                        "code": code,
                        "redirect_uri": settings.slack_redirect_uri,
                    },
                )
            except httpx.HTTPError as exc:
                raise SlackOAuthError(
                    SLACK_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))
                ) from exc

        return _parse_httpx_response(response, _parse_authed_user_response)

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    SLACK_OAUTH_ACCESS_URL,
                    data={
                        "client_id": settings.slack_client_id,
                        "client_secret": settings.slack_client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            except httpx.HTTPError as exc:
                raise SlackOAuthError(
                    SLACK_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))
                ) from exc

        return _parse_httpx_response(response, _parse_refresh_response)

    def callback_error_detail(self, error_code: str) -> str:
        return SLACK_OAUTH_CALLBACK_ERROR_MESSAGES.get(
            error_code, SLACK_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE
        )
