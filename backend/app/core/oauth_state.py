"""Signed, single-use CSRF state for browser-redirect OAuth flows.

Built fresh on this branch rather than stacked on feature/slack-oauth-flow's
unmerged app/core/oauth_state.py (explicit decision -- see
feature/auth-production-readiness's task notes). Deliberately at the same
path to minimize reconciliation surface when the branches eventually merge,
but the shape differs in two ways:

- No `user_id` on the state row. The sibling branch's version is for an
  already-authenticated user's "connect an integration" flow, so it can bind
  the state to `user_id`. A login flow (this one) has no authenticated user
  yet at redirect time -- the state's only job here is proving the callback
  request came from a redirect this app itself issued.
- `purpose` is a plain string, not an Enum shared with another table's type.
  The sibling branch hit a real migration-drift incident from sharing an
  Enum type (`integration_source`) between two tables; a free-form string
  sidesteps that class of bug entirely for a field that's just a label.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.config import settings
from app.core.constants import (
    OAUTH_STATE_ALREADY_USED_MESSAGE, OAUTH_STATE_EXPIRED_MESSAGE, OAUTH_STATE_INVALID_MESSAGE,
    OAUTH_STATE_PURPOSE_MISMATCH_MESSAGE, OAUTH_STATE_TTL_SECONDS,
)
from app.db.session import Base


class OAuthState(Base):
    """Single-use CSRF state issued by a login/connect redirect endpoint.

    `jti` is the nonce embedded in the signed state JWT handed to the
    provider. The JWT signature and `exp` claim prove the state wasn't
    tampered with and hasn't expired, but only this row -- specifically
    `used_at` -- can prove it hasn't already been redeemed once, since a
    JWT alone is stateless and would otherwise be replayable for its whole
    lifetime.
    """

    __tablename__ = "oauth_states"

    id = Column(Integer, primary_key=True)
    jti = Column(String, nullable=False, unique=True, index=True)
    purpose = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OAuthStateError(Exception):
    """Raised when a state parameter fails validation.

    `message` is one of the OAUTH_STATE_*_MESSAGE constants above, specific
    to the failure reason.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def create_oauth_state(db: Session, *, purpose: str) -> str:
    """Issue a signed, single-use state token for `purpose`.

    A row is persisted keyed by the token's `jti` so `consume_oauth_state`
    can enforce single-use -- the JWT signature and `exp` claim alone can't
    do that, since a JWT is stateless and would otherwise be replayable
    until it expires.
    """
    jti = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)

    db.add(OAuthState(jti=jti, purpose=purpose, expires_at=expires_at))
    db.commit()

    payload = {"jti": jti, "purpose": purpose, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def consume_oauth_state(db: Session, *, token: str, expected_purpose: str) -> None:
    """Validate and redeem a state token issued for `expected_purpose`.

    Raises OAuthStateError, with a message specific to the failure reason
    (invalid/tampered signature, expired, already used, or issued for a
    different purpose), rather than a generic rejection.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise OAuthStateError(OAUTH_STATE_EXPIRED_MESSAGE) from exc
    except jwt.PyJWTError as exc:
        raise OAuthStateError(OAUTH_STATE_INVALID_MESSAGE) from exc

    if payload.get("purpose") != expected_purpose:
        raise OAuthStateError(OAUTH_STATE_PURPOSE_MISMATCH_MESSAGE)

    jti = payload.get("jti")
    state_row = db.query(OAuthState).filter(OAuthState.jti == jti).with_for_update().first()
    if state_row is None:
        raise OAuthStateError(OAUTH_STATE_INVALID_MESSAGE)

    if state_row.purpose != expected_purpose:
        raise OAuthStateError(OAUTH_STATE_PURPOSE_MISMATCH_MESSAGE)

    if state_row.used_at is not None:
        raise OAuthStateError(OAUTH_STATE_ALREADY_USED_MESSAGE)

    now = datetime.now(timezone.utc)
    if state_row.expires_at <= now:
        raise OAuthStateError(OAUTH_STATE_EXPIRED_MESSAGE)

    state_row.used_at = now
    db.commit()
