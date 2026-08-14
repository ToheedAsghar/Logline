"""These are one-time passes that let the "Connect" button actually work. Normally, when your browser talks to our
server, it proves who you are with a login token attached to the request. But actually opening a new page (like
navigating to Slack's login screen) is different -- that's a real page visit, not a background request, and a page
visit can't carry that proof along with it the way a normal request can.

So here's the trick: right before the browser navigates away, we quietly ask our own server (using your normal login,
since this part IS a background request) for a temporary one-time code. We stick that code onto the end of the web
address as a query parameter, and the browser carries it there automatically just by visiting the page. Our server sees
the code arrive and accepts it as proof -- but only once, and only for 60 seconds.

This works similarly to how we already handle "reset your password" and "verify your email" links elsewhere in this
project -- a signed, one-time code tied to a database row, marked used after one use. We built this one to be simpler
than the code used later in this same OAuth flow (the one that handles the provider redirecting back to us), because
that one has to wrap around another code and this one doesn't -- it's just a direct, one-time pass.

It uses its own secret signing "flavor" and a much shorter timer (60 seconds, not several minutes) specifically so it
can never accidentally be mixed up with, or reused as, that other code.
"""

from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.models import ConnectLinkToken, IntegrationSource

CONNECT_LINK_TOKEN_SALT = "integration-connect-link"
CONNECT_LINK_TOKEN_TTL_SECONDS = 60


class ConnectLinkTokenError(Exception):
    """Raised when a token can't be accepted. The `reason` field is one of: "expired" (token is too old), "tampered"
    (token signature is invalid), "already_used" (someone already redeemed it), "not_found" (no matching database
    row), or "source_mismatch" (token was for a different provider).
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=CONNECT_LINK_TOKEN_SALT)


def create_connect_link_token(db: Session, *, user_id: int, source: IntegrationSource) -> str:
    """Create a new one-time pass for a browser navigation. Stores a row in the database and returns a signed token
    string that proves this pass exists and is valid when presented later as a query parameter.
    """
    token_row = ConnectLinkToken(user_id=user_id, source=source)
    db.add(token_row)
    db.flush()

    token = _serializer().dumps({"user_id": user_id, "token_id": token_row.id})
    db.commit()
    return token


def consume_connect_link_token(db: Session, *, token: str, expected_source: IntegrationSource) -> int:
    """Redeem a one-time pass if it's valid. Returns the user ID the pass was issued for. Raises ConnectLinkTokenError
    if the token is expired, tampered, already used, doesn't exist, or is for the wrong provider.

    This function locks the database row before marking it used, so two requests arriving at the exact same time
    can't both succeed -- the first one wins, the second gets rejected as "already_used".
    """
    try:
        data = _serializer().loads(token, max_age=CONNECT_LINK_TOKEN_TTL_SECONDS)
    except SignatureExpired:
        raise ConnectLinkTokenError("expired") from None
    except BadSignature:
        raise ConnectLinkTokenError("tampered") from None

    token_id = data.get("token_id")
    token_row = (
        db.query(ConnectLinkToken).filter(ConnectLinkToken.id == token_id).with_for_update().first()
    )
    if token_row is None:
        raise ConnectLinkTokenError("not_found")
    if token_row.source != expected_source:
        raise ConnectLinkTokenError("source_mismatch")
    if token_row.used_at is not None:
        raise ConnectLinkTokenError("already_used")

    token_row.used_at = datetime.now(timezone.utc)
    db.commit()
    return token_row.user_id
