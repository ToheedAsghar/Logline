# OAuth
OAUTH_STATE_TTL_SECONDS = 600

OAUTH_STATE_INVALID_MESSAGE = (
    "Could not verify the OAuth state parameter: it was missing, malformed, or its "
    "signature did not match. Restart the sign-in flow."
)
OAUTH_STATE_EXPIRED_MESSAGE = (
    f"This OAuth state parameter has expired (states are valid for "
    f"{OAUTH_STATE_TTL_SECONDS // 60} minutes). Restart the sign-in flow."
)
