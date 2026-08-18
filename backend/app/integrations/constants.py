"""Centralized long-string constants for the integrations domain (OAuth connect flows, per-provider token refresh).
Follow this pattern for new values rather than inlining error messages/descriptions at their call site.
"""

# --- OAuth token refresh ---

OAUTH_TOKEN_REFRESH_MARGIN_SECONDS = 300

# --- Provider registry error messages ---

OAUTH_PROVIDER_NOT_REGISTERED_MESSAGE = (
    "No OAuth provider is registered for source={source!r}. This source is a valid "
    "IntegrationSource but its connect/refresh flow has not been implemented yet."
)
