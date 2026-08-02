import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import TypeVar

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


def _bcrypt_input(password: str) -> bytes:
    """Hash the password with SHA-256 first so bcrypt always gets short input."""
    digest = hashlib.sha256(password.encode()).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(_bcrypt_input(password), hashed_password.encode())


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


class SignedTokenError(Exception):
    """Base for the signed-token verification errors.

    `reason` is one of "expired" / "tampered" / "already_used" / "not_found"
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class EmailVerificationTokenError(SignedTokenError):
    """Raised by verify_email_verification_token."""


class PasswordResetTokenError(SignedTokenError):
    """Raised by verify_password_reset_token."""


TokenRow = TypeVar("TokenRow", EmailVerificationToken, PasswordResetToken)


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=salt)


def _create_signed_token(db: Session, user_id: int, salt: str, model: type[TokenRow]) -> str:
    """Create a `model` row for `user_id` and return an opaque, signed token string embedding
    {user_id, token_id} for later verification.
    """
    token_row = model(user_id=user_id)
    db.add(token_row)
    db.flush()

    token = _serializer(salt).dumps({"user_id": user_id, "token_id": token_row.id})
    db.commit()
    return token


def _verify_signed_token(
    db: Session, token: str, salt: str, model: type[TokenRow], max_age_seconds: int,
    error_class: type[SignedTokenError],
) -> TokenRow:
    """Unsign `token` (checking signature + max age), look up the row it names, and confirm it
    hasn't already been used.

    Returns the `model` row (its `.user_id` is the verified user) on success. Raises `error_class`
    with a specific `.reason` otherwise -- the signature guarantees the decoded payload wasn't
    forged, so a valid signature is trusted without re-deriving user_id from the row.
    """
    try:
        data = _serializer(salt).loads(token, max_age=max_age_seconds)
    # SignatureExpired subclasses BadSignature, so it must stay the first branch to keep its own reason.
    except SignatureExpired:
        raise error_class("expired") from None
    except BadSignature:
        raise error_class("tampered") from None

    token_id = data.get("token_id")
    token_row = db.query(model).filter(model.id == token_id).first()
    if token_row is None:
        raise error_class("not_found")
    if token_row.used_at is not None:
        raise error_class("already_used")

    return token_row


def create_email_verification_token(db: Session, user_id: int) -> str:
    return _create_signed_token(db, user_id, EMAIL_VERIFICATION_SALT, EmailVerificationToken)


def verify_email_verification_token(db: Session, token: str) -> EmailVerificationToken:
    return _verify_signed_token(
        db, token, EMAIL_VERIFICATION_SALT, EmailVerificationToken,
        EMAIL_VERIFICATION_TOKEN_MAX_AGE_SECONDS, EmailVerificationTokenError,
    )


def create_password_reset_token(db: Session, user_id: int) -> str:
    return _create_signed_token(db, user_id, PASSWORD_RESET_SALT, PasswordResetToken)


def verify_password_reset_token(db: Session, token: str) -> PasswordResetToken:
    return _verify_signed_token(
        db, token, PASSWORD_RESET_SALT, PasswordResetToken,
        PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS, PasswordResetTokenError,
    )
