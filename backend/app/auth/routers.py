import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import crud, google_oauth
from app.auth.constants import (
    EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS, GOOGLE_LOGIN_STATE_PURPOSE, PASSWORD_RESET_RESEND_COOLDOWN_SECONDS,
    REFRESH_TOKEN_COOKIE_NAME, REFRESH_TOKEN_COOKIE_PATH, TEXT_FORGOT_PASSWORD_GENERIC_MESSAGE,
    TEXT_GOOGLE_SIGN_IN_FAILED, TEXT_INACTIVE_USER_ACCOUNT, TEXT_LOGGED_OUT, TEXT_LOGGED_OUT_ALL,
    TEXT_LOGIN_EMAIL_NOT_VERIFIED, TEXT_LOGIN_INVALID_CREDENTIALS, TEXT_PASSWORD_RESET_SUCCESSFULL,
    TEXT_PASSWORD_TOKEN_ERROR, TEXT_REFRESH_TOKEN_CONCURRENT, TEXT_REFRESH_TOKEN_INVALID, TEXT_SIGNUP_GENERIC_MESSAGE,
)
from app.auth.deps import get_current_user
from app.auth.google_oauth import GoogleAuthError
from app.auth.models import EmailVerificationToken, PasswordResetToken, User
from app.auth.schemas import (
    ForgotPasswordRequest, MessageResponse, OAuthExchangeRequest, ResendVerificationRequest, ResetPasswordRequest,
    Token, UserLogin, UserResponse, UserSignup,
)
from app.auth.security import (
    EmailVerificationTokenError, PasswordResetTokenError, create_access_token, create_email_verification_token,
    create_password_reset_token, hash_password, verify_email_verification_token, verify_password,
    verify_password_reset_token,
)
from app.config import ALLOW_INSECURE, settings
from app.core.email import EmailDeliveryError, get_email_provider
from app.core.oauth_state import (
    OAuthStateError, consume_oauth_exchange_code, consume_oauth_state, create_oauth_exchange_code, create_oauth_state,
)
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger(__name__)

TEXT_VERIFICATION_SUBJECT = "Verify your Logline email"
TEXT_PASSWORD_RESET_SUBJECT = "Reset your Logline password"
TEXT_VERIFICATION_TOKEN_ERROR = "Invalid or expired verification link"
TEXT_EMAIL_VERIFIED_SUCCESSFUL = "Email verified successfully"
TEXT_RESEND_VERIFICATION_GENERIC_MESSAGE = (
    "If an account exists for that email and needs verification, a new email has been sent."
)


@dataclass(frozen=True)
class _TokenEmail:
    """The four things that differ between the verification and password-reset emails."""

    kind: str
    path: str
    subject: str
    body: str
    create_token: Callable[[Session, int], str]


_VERIFICATION_EMAIL = _TokenEmail(
    kind="verification",
    path="verify-email",
    subject=TEXT_VERIFICATION_SUBJECT,
    body="Click the link below to verify your email address:\n\n{url}\n\nThis link expires in 24 hours.",
    create_token=create_email_verification_token,
)

_PASSWORD_RESET_EMAIL = _TokenEmail(
    kind="password reset",
    path="reset-password",
    subject=TEXT_PASSWORD_RESET_SUBJECT,
    body=(
        "Click the link below to choose a new password:\n\n{url}\n\n"
        "This link expires in 1 hour. If you didn't request this, you can ignore this email."
    ),
    create_token=create_password_reset_token,
)


async def _send_token_email(user_id: int, email: str, subject: str, body: str, kind: str) -> None:
    """Runs as a FastAPI BackgroundTask, which awaits this coroutine with no try/except of its own
    (starlette.background.BackgroundTask.__call__). A failure here never reaches the original HTTP request -- the
    response was already sent -- so it must be caught and logged here, or it vanishes with no record anywhere.
    """
    provider = get_email_provider()
    try:
        await provider.send(to=email, subject=subject, body=body)
    except EmailDeliveryError as exc:
        logger.error("Failed to send %s email to user_id=%s email=%s: %s", kind, user_id, email, exc, exc_info=True)


def _issue_and_queue_email(db: Session, user: User, background_tasks: BackgroundTasks, spec: _TokenEmail) -> None:
    token = spec.create_token(db, user.id)
    url = f"{settings.frontend_base_url}/{spec.path}?token={token}"
    body = spec.body.format(url=url)
    background_tasks.add_task(_send_token_email, user.id, user.email, spec.subject, body, spec.kind)


def _latest_token(db: Session, model: type[EmailVerificationToken] | type[PasswordResetToken], user_id: int):
    """Return the most recently created `model` row for `user_id`, or None if there is none."""
    return (
        db.query(model)
        .filter(model.user_id == user_id)
        .order_by(model.created_at.desc())
        .first()
    )


def _under_cooldown(last_token, cooldown_seconds: int) -> bool:
    """Whether `last_token` was issued recently enough that another email should be skipped."""
    if last_token is None:
        return False
    elapsed_seconds = (datetime.now(timezone.utc) - last_token.created_at).total_seconds()
    return elapsed_seconds < cooldown_seconds


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Attach the refresh token as an httpOnly cookie, scoped to `/auth` so it is never sent on ordinary API
    requests. `secure` mirrors the same insecure-opt-out `config.py` already uses for the app's base URLs -- every
    real (non-loopback) deployment is HTTPS-only, so `Secure` is safe to set unconditionally there."""
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=REFRESH_TOKEN_COOKIE_PATH,
        httponly=True,
        secure=not ALLOW_INSECURE,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_TOKEN_COOKIE_NAME, path=REFRESH_TOKEN_COOKIE_PATH)


def _refresh_cookie_deletion_headers() -> dict[str, str]:
    """Generates the Set-Cookie deletion header dictionary for HTTPException(headers=...).

    Raising an HTTPException in FastAPI ignores any changes made to the injected Response object. To delete a cookie
    on an error response, the deletion header must be passed directly into the exception. This uses a temporary
    Response object to generate the exact header without duplicating cookie configuration.
    """
    carrier = Response()
    _clear_refresh_cookie(carrier)
    return {"set-cookie": carrier.headers["set-cookie"]}


def _issue_login_response(db: Session, response: Response, user: User) -> Token:
    """Create a fresh refresh-token session for `user`, attach it as a cookie on `response`, and return the access
    token to be sent in the JSON body. Login and Google exchange both funnel through this single path so every
    signed-in session -- password or SSO -- is represented the same way."""
    _, refresh_token = crud.create_session(db, user_id=user.id)
    _set_refresh_cookie(response, refresh_token)
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/signup", response_model=MessageResponse)
def signup(payload: UserSignup, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Same enumeration principle as /forgot-password: the caller must not be able to tell "email already registered"
    from "account created" by status, body, or shape.
    """
    generic_response = MessageResponse(message=TEXT_SIGNUP_GENERIC_MESSAGE)

    try:
        user = crud.create_user(
            db, email=payload.email, hashed_password=hash_password(payload.password), name=payload.name
        )
    except IntegrityError:
        db.rollback()
        return generic_response

    _issue_and_queue_email(db, user, background_tasks, _VERIFICATION_EMAIL)
    return generic_response


@router.get("/verify-email", response_model=MessageResponse)
def verify_email(token: str, db: Session = Depends(get_db)):
    try:
        token_row = verify_email_verification_token(db, token)
    except EmailVerificationTokenError as exc:
        logger.info("Email verification failed: %s", exc.reason)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TEXT_VERIFICATION_TOKEN_ERROR)

    token_row.used_at = datetime.now(timezone.utc)
    user = db.query(User).filter(User.id == token_row.user_id).first()
    user.is_active = True
    db.commit()

    return MessageResponse(message=TEXT_EMAIL_VERIFIED_SUCCESSFUL)


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(
    payload: ResendVerificationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Resend a verification email when the account still needs one.

    The response stays the same in every case so people cannot tell whether the email exists, the account is already
    active, or a new email was sent. If the last verification email was sent too recently, this skips sending a new
    one but still returns the same generic success message.
    """

    user = crud.get_user_by_email(db, payload.email)

    generic_response = MessageResponse(message=TEXT_RESEND_VERIFICATION_GENERIC_MESSAGE)
    if user is None or user.is_active:
        return generic_response

    last_token = _latest_token(db, EmailVerificationToken, user.id)
    if _under_cooldown(last_token, EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS):
        return generic_response

    _issue_and_queue_email(db, user, background_tasks, _VERIFICATION_EMAIL)
    return generic_response


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(payload: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Send a password reset email when the account can use one.

    The reply is always the same so people cannot tell whether the email exists, belongs to an SSO-only account, or
    already has a reset email queued. If the last reset email was sent too recently, this skips sending a new one but
    still returns the same generic message.
    """

    generic_response = MessageResponse(message=TEXT_FORGOT_PASSWORD_GENERIC_MESSAGE)

    user = crud.get_user_by_email(db, payload.email)
    eligible = user is not None and not user.is_sso_user

    if not eligible:
        return generic_response

    last_token = _latest_token(db, PasswordResetToken, user.id)
    if _under_cooldown(last_token, PASSWORD_RESET_RESEND_COOLDOWN_SECONDS):
        return generic_response

    _issue_and_queue_email(db, user, background_tasks, _PASSWORD_RESET_EMAIL)
    return generic_response


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a password with a valid, unused token."""
    try:
        token_row = verify_password_reset_token(db, payload.token)
    except PasswordResetTokenError as exc:
        logger.info("Password reset failed: %s", exc.reason)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TEXT_PASSWORD_TOKEN_ERROR)

    now = datetime.now(timezone.utc)
    claimed = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.id == token_row.id, PasswordResetToken.used_at.is_(None))
        .update({"used_at": now})
    )
    if claimed == 0:
        db.rollback()
        logger.info("Password reset failed: already_used")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TEXT_PASSWORD_TOKEN_ERROR)

    user = db.query(User).filter(User.id == token_row.user_id).first()
    user.hashed_password = hash_password(payload.new_password)

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
    ).update({"used_at": now})

    db.commit()

    return MessageResponse(message=TEXT_PASSWORD_RESET_SUCCESSFULL)


@router.post("/login", response_model=Token)
def login(payload: UserLogin, response: Response, db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, payload.email)
    if user is None or user.hashed_password is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=TEXT_LOGIN_INVALID_CREDENTIALS)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TEXT_LOGIN_EMAIL_NOT_VERIFIED,
        )

    return _issue_login_response(db, response, user)


@router.get("/google/login")
def google_login(db: Session = Depends(get_db)):
    state = create_oauth_state(db, purpose=GOOGLE_LOGIN_STATE_PURPOSE)
    return RedirectResponse(google_oauth.build_authorize_url(state))


@router.get("/google/callback")
def google_callback(
    state: str | None = None, code: str | None = None, error: str | None = None, db: Session = Depends(get_db),
):
    if error or not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TEXT_GOOGLE_SIGN_IN_FAILED)

    try:
        consume_oauth_state(db, token=state, expected_purpose=GOOGLE_LOGIN_STATE_PURPOSE)
    except OAuthStateError as exc:
        logger.info("Google login state validation failed: %s", exc.message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    try:
        id_token = google_oauth.exchange_code_for_id_token(code)
        claims = google_oauth.verify_google_id_token(id_token)
    except GoogleAuthError as exc:
        logger.error("Google login failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TEXT_GOOGLE_SIGN_IN_FAILED)

    google_user_id = claims["sub"]

    email = claims["email"]
    name = claims.get("name")

    user = crud.get_user_by_google_id(db, google_user_id)
    if user is None:
        user = crud.get_user_by_email(db, email)
        if user is None:
            user = crud.create_google_user(db, email=email, google_user_id=google_user_id, name=name)
        else:
            user = crud.link_google_account(db, user, google_user_id=google_user_id)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TEXT_INACTIVE_USER_ACCOUNT)

    exchange_code = create_oauth_exchange_code(db, user_id=user.id)
    return RedirectResponse(f"{settings.frontend_base_url}/oauth/callback#code={exchange_code}")


@router.post("/google/exchange", response_model=Token)
def google_exchange(payload: OAuthExchangeRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user_id = consume_oauth_exchange_code(db, code=payload.code)
    except OAuthStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TEXT_INACTIVE_USER_ACCOUNT)

    return _issue_login_response(db, response, user)


@router.post("/refresh", response_model=Token)
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    """Exchanges the refresh-token cookie for a new access token and rotates the refresh token.

    Does not require an Authorization header because its purpose is to get a new access token after the old one has
    expired. A dead token (missing, unknown, expired, or replayed outside the reuse grace window) returns 401 and
    clears the cookie. A token replayed inside the grace window -- almost certainly a second tab racing the same
    rotation, not theft -- returns 409 and leaves the cookie alone, telling the caller to retry rather than log out.
    On success, the response sets a new refresh cookie.
    """
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=TEXT_REFRESH_TOKEN_INVALID)

    result = crud.rotate_session(db, refresh_token=refresh_token)
    if result.outcome is crud.RotationOutcome.CONCURRENT_ROTATION:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=TEXT_REFRESH_TOKEN_CONCURRENT)

    if result.outcome is not crud.RotationOutcome.ROTATED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=TEXT_REFRESH_TOKEN_INVALID,
            headers=_refresh_cookie_deletion_headers() if result.clear_refresh_cookie else None,
        )

    _set_refresh_cookie(response, result.token)
    return Token(access_token=create_access_token(result.session.user_id))


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    """Revoke the caller's own refresh-token session, if the cookie names a live one, and clear the cookie either
    way. No `Authorization` bearer required -- a client logging out with an already-expired access token must still
    be able to revoke its refresh token."""
    if refresh_token is not None:
        crud.revoke_session_by_token(db, refresh_token=refresh_token)
    _clear_refresh_cookie(response)
    return MessageResponse(message=TEXT_LOGGED_OUT)


@router.post("/logout-all", response_model=MessageResponse)
def logout_all(
    response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Revoke every refresh-token session for the current user ("log out of all devices"), including the caller's
    own -- the caller's access token keeps working until it naturally expires (at most `jwt_expire_minutes`
    minutes), same bound as a single-session logout."""
    crud.revoke_all_sessions(db, user_id=current_user.id)
    _clear_refresh_cookie(response)
    return MessageResponse(message=TEXT_LOGGED_OUT_ALL)
