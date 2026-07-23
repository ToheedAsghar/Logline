"""Centralized long-string constants for the integrations domain (OAuth
connect flows, per-provider token refresh). Follow this pattern for new
values rather than inlining error messages/descriptions at their call site.
"""

# --- OAuth token refresh ---

OAUTH_TOKEN_REFRESH_MARGIN_SECONDS = 300

# --- Slack OAuth endpoints/scopes ---

SLACK_OAUTH_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_ACCESS_URL = "https://slack.com/api/oauth.v2.access"

SLACK_OAUTH_USER_SCOPES = (
    "channels:read",
    "channels:history",
    "groups:history",
    "im:read",
)

SLACK_CONNECT_STATE_PURPOSE = "slack_connect"

# --- Messages ---

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
"""Maps Slack's `error` query-param values to fixed, internal-facing redirect
messages -- the raw provider string is never reflected into the redirect URL
directly. Unrecognized codes fall back to SLACK_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE."""

OAUTH_PROVIDER_NOT_REGISTERED_MESSAGE = (
    "No OAuth provider is registered for source={source!r}. This source is a valid "
    "IntegrationSource but its connect/refresh flow has not been implemented yet."
)
