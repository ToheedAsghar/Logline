"""Manages OAuth state tokens for "connect integration" flows, where an
already-authenticated user authorizes an external service (like Slack).

The challenge: oauth_state.py's table has no user_id column, which works
for login flows (no user exists yet at OAuth callback time). But for
connecting an integration, we need to remember which user initiated the flow.

Solution: wrap the core oauth_state token in a signed outer envelope that
carries the user_id. The envelope is cryptographically signed and expires
quickly, so even if tampered with, it will be rejected. The inner state
token works exactly as before -- same security checks, same single-use
enforcement, same expiry rules.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.core.constants import OAUTH_STATE_EXPIRED_MESSAGE, OAUTH_STATE_INVALID_MESSAGE, OAUTH_STATE_TTL_SECONDS
from app.core.oauth_state import OAuthStateError, consume_oauth_state, create_oauth_state
from app.integrations.models import IntegrationSource

CONNECT_STATE_SALT = "integration-connect-state"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=CONNECT_STATE_SALT)


def _connect_purpose(source: IntegrationSource) -> str:
    return f"{source.value}_connect"


def create_connect_state(db: Session, *, user_id: int, source: IntegrationSource) -> str:
    """Issue a signed, single-use connect-flow state token binding `user_id`
    to `source`, for an already-authenticated user's "Connect X" click.
    """
    inner_token = create_oauth_state(db, purpose=_connect_purpose(source))
    return _serializer().dumps({"user_id": user_id, "inner_token": inner_token})


def consume_connect_state(db: Session, *, token: str, expected_source: IntegrationSource) -> int:
    """Validate and redeem a connect-flow state token, returning the user_id
    it was issued for.

    Raises OAuthStateError -- the same exception type core/oauth_state.py
    itself raises -- so callers only need to catch one type regardless of
    which layer (this envelope, or the inner state) failed.
    """
    try:
        data = _serializer().loads(token, max_age=OAUTH_STATE_TTL_SECONDS)
    except SignatureExpired:
        raise OAuthStateError(OAUTH_STATE_EXPIRED_MESSAGE) from None
    except BadSignature:
        raise OAuthStateError(OAUTH_STATE_INVALID_MESSAGE) from None

    inner_token = data.get("inner_token")
    user_id = data.get("user_id")
    if inner_token is None or user_id is None:
        raise OAuthStateError(OAUTH_STATE_INVALID_MESSAGE)

    consume_oauth_state(db, token=inner_token, expected_purpose=_connect_purpose(expected_source))
    return user_id
