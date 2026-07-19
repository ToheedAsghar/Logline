from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.auth.constants import (
    EMAIL_VERIFICATION_SALT, EMAIL_VERIFICATION_TOKEN_MAX_AGE_SECONDS, PASSWORD_RESET_SALT,
    PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS,
)
from app.auth.models import EmailVerificationToken, PasswordResetToken
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


class EmailVerificationTokenError(Exception):
    """Raised by verify_email_verification_token.

    `reason` is one of "expired" / "tampered" / "already_used" / "not_found"
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _email_verification_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=EMAIL_VERIFICATION_SALT)


def create_email_verification_token(db: Session, user_id: int) -> str:
    """Create an EmailVerificationToken row for `user_id` and return an opaque,
    signed token string embedding {user_id, token_id} for later verification.
    """
    token_row = EmailVerificationToken(user_id=user_id)
    db.add(token_row)
    db.commit()
    db.refresh(token_row)

    serializer = _email_verification_serializer()
    return serializer.dumps({"user_id": user_id, "token_id": token_row.id})


def verify_email_verification_token(db: Session, token: str) -> EmailVerificationToken:
    """Unsign `token` (checking signature + max age), look up the row it names,
    and confirm it hasn't already been used.

    Returns the EmailVerificationToken row (its `.user_id` is the verified
    user) on success. Raises EmailVerificationTokenError with a specific
    `.reason` otherwise -- the signature guarantees the decoded payload wasn't
    forged, so a valid signature is trusted without re-deriving user_id from
    the row.
    """
    serializer = _email_verification_serializer()
    try:
        data = serializer.loads(token, max_age=EMAIL_VERIFICATION_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        raise EmailVerificationTokenError("expired") from None
    except BadSignature:
        raise EmailVerificationTokenError("tampered") from None

    token_id = data.get("token_id")
    token_row = db.query(EmailVerificationToken).filter(EmailVerificationToken.id == token_id).first()
    if token_row is None:
        raise EmailVerificationTokenError("not_found")
    if token_row.used_at is not None:
        raise EmailVerificationTokenError("already_used")

    return token_row


class PasswordResetTokenError(Exception):
    """Raised by verify_password_reset_token.

    `reason` is one of "expired" / "tampered" / "already_used" / "not_found"
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _password_reset_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=PASSWORD_RESET_SALT)


def create_password_reset_token(db: Session, user_id: int) -> str:
    """Create a PasswordResetToken row for `user_id` and return an opaque,
    signed token string embedding {user_id, token_id} for later verification.
    """
    token_row = PasswordResetToken(user_id=user_id)
    db.add(token_row)
    db.commit()
    db.refresh(token_row)

    serializer = _password_reset_serializer()
    return serializer.dumps({"user_id": user_id, "token_id": token_row.id})


def verify_password_reset_token(db: Session, token: str) -> PasswordResetToken:
    """Check the token, find the reset row, and make sure it was not used."""

    serializer = _password_reset_serializer()
    try:
        data = serializer.loads(token, max_age=PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        raise PasswordResetTokenError("expired") from None
    except BadSignature:
        raise PasswordResetTokenError("tampered") from None

    token_id = data.get("token_id")
    token_row = db.query(PasswordResetToken).filter(PasswordResetToken.id == token_id).first()
    if token_row is None:
        raise PasswordResetTokenError("not_found")
    if token_row.used_at is not None:
        raise PasswordResetTokenError("already_used")

    return token_row
