"""Auth for the "actual connection handoff" step of integration setup.

When a user clicks "Connect GitHub" or similar, we need to send them to
GitHub's login screen. The problem: that's a real page visit (the browser's
address bar actually changes), and a real page visit can't carry our login
token along with it -- it can only pass a URL query parameter. But we still
need to prove who the user is, so we let them use either our standard login
token (via an Authorization header, useful for testing) or a one-time pass
that was minted just before the navigation (as a URL query parameter).

This dependency (get_connect_endpoint_user) accepts either one to authenticate
the request, mirroring the behavior of our standard auth checker but loosening
it just enough to handle browser navigation.
"""

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.constants import TEXT_UNAUTHORIZED
from app.auth.models import User
from app.auth.security import decode_access_token
from app.db.session import get_db
from app.integrations.connect_link_token import ConnectLinkTokenError, consume_connect_link_token
from app.integrations.models import IntegrationSource

_optional_bearer_scheme = HTTPBearer(auto_error=False)


def get_connect_endpoint_user(
    source: IntegrationSource,
    token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Find and return the user making this request. Accepts proof in two forms:
    a normal bearer token in the Authorization header (which works for tests or
    programmatic calls), or a one-time pass in the `token` URL query parameter
    (which works for real browser navigation). The bearer token takes priority
    if both somehow arrive. Raises 401 if neither is present, valid, or if the
    user is inactive.

    WARNING: Do NOT reuse this dependency or its header-OR-query-token pattern
    on any other endpoint without a security review first. This pattern is ONLY
    safe here because this specific endpoint:
    (a) consumes the token before producing any response (invalidating it for logs/history),
    (b) is an HTTP redirect, not a data-returning endpoint, and
    (c) the query token is single-use, 60-second TTL, and source-scoped.
    An endpoint lacking any of those three properties MUST NOT copy this dual-auth pattern.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=TEXT_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is not None:
        try:
            user_id = decode_access_token(credentials.credentials)
        except jwt.PyJWTError:
            raise unauthorized
    elif token is not None:
        try:
            user_id = consume_connect_link_token(db, token=token, expected_source=source)
        except ConnectLinkTokenError:
            raise unauthorized from None
    else:
        raise unauthorized

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise unauthorized

    return user
