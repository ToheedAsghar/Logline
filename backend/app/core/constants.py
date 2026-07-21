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
OAUTH_STATE_ALREADY_USED_MESSAGE = (
    "This OAuth state parameter has already been used. Each state is single-use; "
    "restart the sign-in flow to get a new one."
)
OAUTH_STATE_PURPOSE_MISMATCH_MESSAGE = (
    "This OAuth state parameter was issued for a different purpose than the one "
    "being completed. Restart the sign-in flow."
)
