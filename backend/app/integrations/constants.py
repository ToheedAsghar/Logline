"""All the long text strings we show to users in the integrations feature:
error messages when OAuth fails, URLs for connecting to providers, and other
configuration. Keeping them here instead of scattering them through code makes
it easier to update messages or add a new provider.
"""

# --- OAuth token refresh ---

OAUTH_TOKEN_REFRESH_MARGIN_SECONDS = 300

# --- Connect-link tokens ---

CONNECT_LINK_TOKEN_SALT = "integration-connect-link"
CONNECT_LINK_TOKEN_TTL_SECONDS = 60

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

OAUTH_PROVIDER_NOT_REGISTERED_MESSAGE = (
    "No OAuth provider is registered for source={source!r}. This source is a valid "
    "IntegrationSource but its connect/refresh flow has not been implemented yet."
)

# --- GitHub OAuth endpoints/scopes ---

GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"

GITHUB_OAUTH_SCOPES = ("repo",)

GITHUB_CONNECT_STATE_PURPOSE = "github_connect"

# --- Messages ---

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

# --- Jira (Atlassian) OAuth 2.0 (3LO) endpoints/scopes ---

JIRA_OAUTH_AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
JIRA_OAUTH_TOKEN_URL = "https://auth.atlassian.com/oauth/token"

JIRA_OAUTH_SCOPES = ("read:jira-work", "read:jira-user", "offline_access")

JIRA_CONNECT_STATE_PURPOSE = "jira_connect"

# --- Messages ---

JIRA_TOKEN_EXCHANGE_FAILED_MESSAGE = (
    "Jira rejected the authorization_code exchange: {jira_error}. This usually means "
    "the authorization code already expired or was already used. Restart the connect "
    "flow from the Integrations page."
)

JIRA_TOKEN_REFRESH_FAILED_MESSAGE = (
    "Jira rejected the refresh_token exchange: {jira_error}. Atlassian's refresh "
    "tokens rotate on every use and expire after 90 days of inactivity, so the stored "
    "one may have already been superseded, expired, or revoked -- reconnect Jira "
    "from the Integrations page."
)

JIRA_OAUTH_NETWORK_ERROR_MESSAGE = (
    "Could not reach Jira to complete the OAuth request: {detail}. Check network "
    "connectivity and try again."
)

JIRA_MISSING_ACCESS_TOKEN_MESSAGE = (
    "Jira's response did not include an access token. This app's Atlassian OAuth "
    "2.0 (3LO) app configuration is likely missing the required scopes ({scopes}) -- "
    "check its settings before retrying the connect flow."
).format(scopes=", ".join(JIRA_OAUTH_SCOPES))

JIRA_RESPONSE_MISSING_REFRESH_TOKEN_MESSAGE = (
    "Jira's token response did not include a refresh_token. Atlassian only issues one "
    "when `offline_access` is granted, and its refresh tokens rotate on every use -- "
    "without a fresh one here the connection could not be renewed again, so this is "
    "refused rather than silently stored. This app's Atlassian OAuth 2.0 (3LO) app is "
    "likely missing the `offline_access` scope; check its settings, then reconnect Jira "
    "from the Integrations page."
)

JIRA_MALFORMED_RESPONSE_MESSAGE = (
    "Jira returned a response that could not be parsed as the expected token JSON: "
    "{detail}. This is unexpected from Atlassian's token endpoint -- restart the connect "
    "flow from the Integrations page, and if it persists the endpoint may be having "
    "issues."
)

JIRA_TOKEN_NOT_FOUND_MESSAGE = (
    "No stored Jira OAuth token was found for integration_id={integration_id}. The "
    "user needs to connect Jira from the Integrations page before this token can be "
    "refreshed."
)

JIRA_TOKEN_MISSING_REFRESH_TOKEN_MESSAGE = (
    "The stored Jira token for integration_id={integration_id} is near/past expiry "
    "but has no refresh_token on file, so it can't be silently refreshed. The user "
    "needs to reconnect Jira from the Integrations page."
)

JIRA_TOKEN_REFRESH_PERSIST_FAILED_MESSAGE = (
    "Could not persist the refreshed Jira token pair for integration_id={integration_id} "
    "after Atlassian rotated the credentials. Reconnect Jira from the Integrations page."
)

JIRA_CALLBACK_MISSING_PARAMS_MESSAGE = (
    "Jira's callback did not include both `code` and `state` -- the connect flow "
    "did not complete. Restart it from the Integrations page."
)

JIRA_OAUTH_ACCESS_DENIED_MESSAGE = (
    "Jira authorization was not granted -- the connect flow was cancelled. Restart "
    "it from the Integrations page if you'd like to connect Jira."
)

JIRA_OAUTH_UNKNOWN_CALLBACK_ERROR_MESSAGE = (
    "Jira's callback reported an error completing the connect flow. Restart it "
    "from the Integrations page."
)

JIRA_OAUTH_CALLBACK_ERROR_MESSAGES = {
    "access_denied": JIRA_OAUTH_ACCESS_DENIED_MESSAGE,
}
