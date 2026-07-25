"""Defines exceptions for OAuth token refresh operations across different integration providers (Slack, GitHub, Jira,
etc.).

TokenRefreshError is the main exception type that callers should catch when OAuth token operations fail. Each provider
(Slack, GitHub, etc.) defines its own subclass (like SlackOAuthError) that inherits from TokenRefreshError. This way,
callers can catch just the base type and don't need to know which specific provider failed -- the error carries a
`source` field saying "slack", "github", etc.

Every subclass must pass both a `source` string (which provider) and a `message` string (what went wrong) to the base
exception __init__.
"""


class TokenRefreshError(Exception):
    """Base for provider-specific OAuth token-refresh failures.

    Requires both `source` (which integration's provider failed, e.g. "slack") and `message` (an informative,
    user-facing reason) -- a caller that only catches this base type still needs to know which integration failed,
    not just why.
    """

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        self.message = message
        super().__init__(message)
