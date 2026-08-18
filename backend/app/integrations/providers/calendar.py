"""Google Calendar OAuth provider: builds authorization URLs and exchanges authorization codes for access tokens. All
Calendar-specific logic is here (API endpoints, error response formats, how to parse responses, token refresh) so the
generic connect and token-refresh routes don't need to know about individual providers.

Google's OAuth flow differs from the other providers in a few ways that shape this module:

- Shared client, separate redirect URI: this reuses the same Google OAuth client as sign-in
  (`app/auth/google_oauth.py`), because both are the same Google Cloud project. Only the redirect URI differs, and
  `settings.calendar_redirect_uri` must be registered in the Google Cloud Console for the connect flow to work.
- Refresh tokens are issued once, not rotated: Google only returns a refresh_token when `access_type=offline` is
  requested AND the user is being prompted for consent, and it does not return a new one on subsequent refreshes.
  So the initial exchange requires one and refresh responses are expected to omit it -- `ensure_token_fresh` keeps
  the stored one when a refresh response has none.
- Error shape: Google returns real HTTP error status codes with `{error, error_description}` in the body, like Jira
  and unlike Slack/GitHub (which answer HTTP 200 even on rejection).
- Read-only by design: the single requested scope grants reading events and nothing else. This app never writes
  calendar events, so widening this scope would grant access the app has no code path to use.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.integrations.errors import TokenRefreshError
from app.integrations.models import IntegrationSource
from app.integrations.providers.base import OAuthProvider, OAuthTokens

CALENDAR_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
CALENDAR_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

CALENDAR_OAUTH_SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)

CALENDAR_TOKEN_EXCHANGE_FAILED_MESSAGE = (
    "Google rejected the authorization_code exchange: {calendar_error}. This usually "
    "means the authorization code already expired or was already used. Restart the "
    "connect flow from the Integrations page."
)

CALENDAR_TOKEN_REFRESH_FAILED_MESSAGE = (
    "Google rejected the refresh_token exchange: {calendar_error}. The stored refresh "
    "token may have been revoked (e.g. the user removed this app from their Google "
    "account) -- reconnect Calendar from the Integrations page."
)

CALENDAR_OAUTH_NETWORK_ERROR_MESSAGE = (
    "Could not reach Google to complete the OAuth request: {detail}. Check network "
    "connectivity and try again."
)

CALENDAR_MISSING_ACCESS_TOKEN_MESSAGE = (
    "Google's response did not include an access token. This app's Google OAuth client "
    "configuration is likely missing the required scopes ({scopes}) -- check its "
    "settings before retrying the connect flow."
).format(scopes=", ".join(CALENDAR_OAUTH_SCOPES))

CALENDAR_RESPONSE_MISSING_REFRESH_TOKEN_MESSAGE = (
    "Google's token response did not include a refresh_token. Google only issues one "
    "when `access_type=offline` is requested and the user is actually prompted for "
    "consent -- without it the connection would stop working within the hour and could "
    "not be renewed, so this is refused rather than silently stored. Reconnect Calendar "
    "from the Integrations page, and if it persists, revoke this app under the Google "
    "account's third-party access settings so the consent prompt is shown again."
)

CALENDAR_MALFORMED_RESPONSE_MESSAGE = (
    "Google returned a response that could not be parsed as the expected token JSON: "
    "{detail}. This is unexpected from Google's token endpoint -- restart the connect "
    "flow from the Integrations page, and if it persists the endpoint may be having "
    "issues."
)

CALENDAR_TOKEN_NOT_FOUND_MESSAGE = (
    "No stored Calendar OAuth token was found for integration_id={integration_id}. The "
    "user needs to connect Calendar from the Integrations page before this token can be "
    "refreshed."
)

CALENDAR_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE = (
    "The stored Calendar token for integration_id={integration_id} is near/past expiry "
    "but has no refresh_token on file, so it can't be silently refreshed. The user "
    "needs to reconnect Calendar from the Integrations page."
)

CALENDAR_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE = (
    "Could not persist the refreshed Calendar token for integration_id={integration_id} "
    "after Google issued new credentials. Reconnect Calendar from the Integrations page."
)

CALENDAR_CALLBACK_MISSING_PARAMS_MESSAGE = (
    "Google's callback did not include both `code` and `state` -- the connect flow "
    "did not complete. Restart it from the Integrations page."
)

CALENDAR_OAUTH_ACCESS_DENIED_MESSAGE = (
    "Calendar authorization was not granted -- the connect flow was cancelled. Restart "
    "it from the Integrations page if you'd like to connect Calendar."
)

CALENDAR_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE = (
    "Google's callback reported an error completing the connect flow. Restart it "
    "from the Integrations page."
)

CALENDAR_OAUTH_CALLBACK_ERROR_MESSAGES = {
    "access_denied": CALENDAR_OAUTH_ACCESS_DENIED_MESSAGE,
}


class CalendarOAuthError(TokenRefreshError):
    """Raised when Google rejects a Calendar OAuth request or the request can't be sent."""

    def __init__(self, message: str) -> None:
        super().__init__(source=IntegrationSource.calendar.value, message=message)


def _compute_expires_at(expires_in: int | None) -> datetime | None:
    if expires_in is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _parse_token_response(data: dict, *, require_refresh_token: bool) -> OAuthTokens:
    """Extract access token, refresh token, and expiry from Google's response. Used by both the initial code exchange
    and token refresh flows, since both return the same flat structure.

    The initial exchange demands a refresh_token (`require_refresh_token=True`); a refresh does not, because Google
    reuses the original refresh token rather than rotating it and simply omits the field on renewal.
    """
    access_token = data.get("access_token")
    if not access_token:
        raise CalendarOAuthError(CALENDAR_MISSING_ACCESS_TOKEN_MESSAGE)

    refresh_token = data.get("refresh_token")
    if require_refresh_token and not refresh_token:
        raise CalendarOAuthError(CALENDAR_RESPONSE_MISSING_REFRESH_TOKEN_MESSAGE)

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
        return "unknown_error"
    if not isinstance(data, dict):
        return "unknown_error"
    return data.get("error_description") or data.get("error", "unknown_error")


def _parse_httpx_response(
    response: httpx.Response, *, failed_message: str, require_refresh_token: bool
) -> OAuthTokens:
    """Parse a token-exchange/refresh response, raising `CalendarOAuthError` on any failure.

    A 2xx response whose body isn't the expected token JSON is a malformed *received* response, not a transport
    failure -- it's raised via `CALENDAR_MALFORMED_RESPONSE_MESSAGE`, not `failed_message`, so callers don't mistake
    it for "could not reach Google".
    """
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise CalendarOAuthError(failed_message.format(calendar_error=_extract_error_detail(response))) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise CalendarOAuthError(CALENDAR_MALFORMED_RESPONSE_MESSAGE.format(detail=str(exc))) from exc

    if not isinstance(data, dict):
        raise CalendarOAuthError(
            CALENDAR_MALFORMED_RESPONSE_MESSAGE.format(
                detail=f"expected a JSON object, got {type(data).__name__}"
            )
        )

    return _parse_token_response(data, require_refresh_token=require_refresh_token)


class CalendarOAuthProvider(OAuthProvider):
    """Google Calendar's implementation of the shared OAuthProvider interface.

    The generic routes for connecting and refreshing tokens call ONLY this class and the helper functions above. This
    ensures Calendar-specific logic (the correct endpoints, how to parse responses, error handling) lives in one place
    and doesn't leak into shared route code.
    """

    source = IntegrationSource.calendar
    error_type = CalendarOAuthError

    token_not_found_message = CALENDAR_TOKEN_NOT_FOUND_MESSAGE
    missing_refresh_token_message = CALENDAR_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE
    persist_failed_message = CALENDAR_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE
    missing_params_message = CALENDAR_CALLBACK_MISSING_PARAMS_MESSAGE

    def build_authorize_url(self, state: str) -> str:
        """Build Google's consent URL.

        `access_type=offline` with `prompt=consent` is what makes Google return a refresh_token; without both, a
        returning user who already consented gets an access token that expires in an hour with no way to renew it.
        """
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.calendar_redirect_uri,
            "response_type": "code",
            "scope": " ".join(CALENDAR_OAUTH_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{CALENDAR_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    CALENDAR_OAUTH_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "code": code,
                        "redirect_uri": settings.calendar_redirect_uri,
                    },
                )
            except httpx.HTTPError as exc:
                raise CalendarOAuthError(CALENDAR_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))) from exc

        return _parse_httpx_response(
            response, failed_message=CALENDAR_TOKEN_EXCHANGE_FAILED_MESSAGE, require_refresh_token=True
        )

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    CALENDAR_OAUTH_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "refresh_token": refresh_token,
                    },
                )
            except httpx.HTTPError as exc:
                raise CalendarOAuthError(CALENDAR_OAUTH_NETWORK_ERROR_MESSAGE.format(detail=str(exc))) from exc

        return _parse_httpx_response(
            response, failed_message=CALENDAR_TOKEN_REFRESH_FAILED_MESSAGE, require_refresh_token=False
        )

    def callback_error_detail(self, error_code: str) -> str:
        return CALENDAR_OAUTH_CALLBACK_ERROR_MESSAGES.get(error_code, CALENDAR_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE)
