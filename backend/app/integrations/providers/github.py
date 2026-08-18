"""GitHub OAuth provider: builds authorization URLs and exchanges authorization codes for access tokens. All
GitHub-specific logic is here (API endpoints, error response formats, how to parse responses) so the generic connect
and token-refresh routes don't need to know about individual providers.

Unlike Slack, GitHub's "OAuth Apps" (the standard OAuth app type, not the newer "GitHub Apps") issue access tokens
that never expire. This means there's nothing to refresh -- the token from the initial exchange remains valid
indefinitely. The refresh() method raises an error instead of making a network call, since refresh attempts should
never happen for GitHub tokens (and if they do, that's a real bug worth surfacing loudly).
"""

from urllib.parse import urlencode

import httpx

from app.config import settings
from app.integrations.errors import TokenRefreshError
from app.integrations.models import IntegrationSource
from app.integrations.providers.base import OAuthProvider, OAuthTokens

GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"

GITHUB_OAUTH_SCOPES = ("repo",)

GITHUB_TOKEN_EXCHANGE_FAILED_MESSAGE = (
    "GitHub rejected the access_token request: {github_error}. This usually means the "
    "authorization code already expired or was already used. Restart the connect "
    "flow from the Integrations page."
)

GITHUB_OAUTH_NETWORK_ERROR_MESSAGE = (
    "Could not reach GitHub to complete the OAuth request: {detail}. Check network "
    "connectivity and try again."
)

GITHUB_MISSING_ACCESS_TOKEN_MESSAGE = (
    "GitHub's response did not include an access token. This app's GitHub OAuth App "
    "configuration is likely missing the required scopes ({scopes}) -- check its "
    "settings before retrying the connect flow."
).format(scopes=", ".join(GITHUB_OAUTH_SCOPES))

GITHUB_TOKEN_NOT_FOUND_MESSAGE = (
    "No stored GitHub OAuth token was found for integration_id={integration_id}. The "
    "user needs to connect GitHub from the Integrations page before this token can be "
    "refreshed."
)

GITHUB_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE = (
    "The stored GitHub token for integration_id={integration_id} has no refresh_token "
    "on file. GitHub OAuth Apps don't issue refresh tokens -- their access tokens "
    "don't expire, so this should not happen. If GitHub revoked the token, the user "
    "needs to reconnect GitHub from the Integrations page."
)

GITHUB_REFRESH_NOT_SUPPORTED_MESSAGE = (
    "GitHub OAuth Apps don't support refreshing access tokens -- tokens from the "
    "initial exchange don't expire, so there is nothing to refresh. If this was "
    "reached, the stored token may have been revoked; reconnect GitHub from the "
    "Integrations page instead."
)

GITHUB_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE = (
    "Could not persist the refreshed GitHub token pair for integration_id={integration_id} "
    "after GitHub rotated the credentials. Reconnect GitHub from the Integrations page."
)

GITHUB_CALLBACK_MISSING_PARAMS_MESSAGE = (
    "GitHub's callback did not include both `code` and `state` -- the connect flow "
    "did not complete. Restart it from the Integrations page."
)

GITHUB_OAUTH_ACCESS_DENIED_MESSAGE = (
    "GitHub authorization was not granted -- the connect flow was cancelled. Restart "
    "it from the Integrations page if you'd like to connect GitHub."
)

GITHUB_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE = (
    "GitHub's callback reported an error completing the connect flow. Restart it "
    "from the Integrations page."
)

GITHUB_OAUTH_CALLBACK_ERROR_MESSAGES = {
    "access_denied": GITHUB_OAUTH_ACCESS_DENIED_MESSAGE,
}


class GitHubOAuthError(TokenRefreshError):
    """Raised when GitHub rejects an OAuth request or the request can't be sent."""

    def __init__(self, message: str) -> None:
        super().__init__(source=IntegrationSource.github.value, message=message)


def _parse_token_response(data: dict) -> OAuthTokens:
    """Parse GitHub's response after exchanging an authorization code for an access token. GitHub returns HTTP 200
    even on rejection -- errors surface as an `error` field in the (JSON, given `Accept: application/json`) body, not
    as an HTTP status code.
    """
    if "error" in data:
        raise GitHubOAuthError(
            GITHUB_TOKEN_EXCHANGE_FAILED_MESSAGE.format(
                github_error=data.get("error_description") or data.get("error", "unknown_error"),
            )
        )

    access_token = data.get("access_token")
    if not access_token:
        raise GitHubOAuthError(GITHUB_MISSING_ACCESS_TOKEN_MESSAGE)

    return OAuthTokens(
        access_token=access_token,
        scope=data.get("scope", ""),
    )


def _parse_httpx_response(response: httpx.Response) -> OAuthTokens:
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise GitHubOAuthError(GITHUB_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise GitHubOAuthError(GITHUB_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))) from exc

    return _parse_token_response(data)


class GitHubOAuthProvider(OAuthProvider):
    """GitHub's implementation of the shared OAuthProvider interface."""

    source = IntegrationSource.github
    error_type = GitHubOAuthError

    token_not_found_message = GITHUB_TOKEN_NOT_FOUND_MESSAGE
    missing_refresh_token_message = GITHUB_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE
    persist_failed_message = GITHUB_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE
    missing_params_message = GITHUB_CALLBACK_MISSING_PARAMS_MESSAGE

    def build_authorize_url(self, state: str) -> str:
        params = {
            "client_id": settings.github_client_id,
            "scope": " ".join(GITHUB_OAUTH_SCOPES),
            "redirect_uri": settings.github_redirect_uri,
            "state": state,
        }
        return f"{GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    GITHUB_OAUTH_ACCESS_TOKEN_URL,
                    data={
                        "client_id": settings.github_client_id,
                        "client_secret": settings.github_client_secret,
                        "code": code,
                        "redirect_uri": settings.github_redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise GitHubOAuthError(GITHUB_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))) from exc

        return _parse_httpx_response(response)

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        """GitHub OAuth Apps never need token refresh since access tokens don't expire. In normal operation, this is
        never called -- the token-refresh flow checks if a token has an expiry time, and GitHub tokens never do. This
        method raises an error instead of silently succeeding, so if it ever gets called, we surface the unexpected
        situation loudly.
        """
        raise GitHubOAuthError(GITHUB_REFRESH_NOT_SUPPORTED_MESSAGE)

    def callback_error_detail(self, error_code: str) -> str:
        return GITHUB_OAUTH_CALLBACK_ERROR_MESSAGES.get(error_code, GITHUB_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE)
