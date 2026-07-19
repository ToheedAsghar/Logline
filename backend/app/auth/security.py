from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed_password.encode())


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    """Return the user_id encoded in `token`.

    Raises jwt.PyJWTError (or a subclass) if the token is expired, malformed,
    has an invalid signature, or carries a missing/non-numeric `sub` claim --
    callers (e.g. get_current_user) only need to catch jwt.PyJWTError to
    treat every one of those cases as an unauthenticated request.
    """
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    sub = payload.get("sub")
    if sub is None:
        raise jwt.InvalidTokenError("Token is missing the 'sub' claim")
    try:
        return int(sub)
    except (TypeError, ValueError):
        raise jwt.InvalidTokenError("Token 'sub' claim is not numeric") from None
