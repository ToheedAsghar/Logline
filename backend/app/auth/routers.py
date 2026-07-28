import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import crud, google_oauth
from app.auth.constants import (
    EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS, GOOGLE_LOGIN_STATE_PURPOSE, PASSWORD_RESET_RESEND_COOLDOWN_SECONDS,
    TEXT_FORGOT_PASSWORD_GENERIC_MESSAGE, TEXT_GOOGLE_SIGN_IN_FAILED, TEXT_LOGIN_EMAIL_NOT_VERIFIED,
    TEXT_LOGIN_INVALID_CREDENTIALS, TEXT_PASSWORD_RESET_SUBJECT, TEXT_PASSWORD_RESET_SUCCESSFULL,
    TEXT_PASSWORD_TOKEN_ERROR, TEXT_SIGNUP_GENERIC_MESSAGE,
)
from app.auth.deps import get_current_user
from app.auth.google_oauth import GoogleAuthError
from app.auth.models import EmailVerificationToken, PasswordResetToken, User
from app.auth.schemas import (
    ForgotPasswordRequest, MessageResponse, ResendVerificationRequest, ResetPasswordRequest, Token, UserLogin,
    UserResponse, UserSignup,
)
from app.auth.security import (
    EmailVerificationTokenError, PasswordResetTokenError, create_access_token, create_email_verification_token,
    create_password_reset_token, hash_password, verify_email_verification_token, verify_password,
    verify_password_reset_token,
)
from app.config import settings
from app.core.email import EmailDeliveryError, get_email_provider
from app.core.oauth_state import OAuthStateError, consume_oauth_state, create_oauth_state
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger(__name__)


async def _send_verification_email(user_id: int, email: str, token: str) -> None:
    """Runs as a FastAPI BackgroundTask, which awaits this coroutine with no
    try/except of its own (starlette.background.BackgroundTask.__call__).
    A failure here never reaches the original HTTP request -- the response
    was already sent -- so it must be caught and logged here, or it vanishes
    with no record anywhere.
    """
    verify_url = f"{settings.frontend_base_url}/verify-email?token={token}"
    provider = get_email_provider()
    try:
        await provider.send(
            to=email,
            subject="Verify your Logline email",
            body=(
                "Click the link below to verify your email address:\n\n"
                f"{verify_url}\n\n"
                "This link expires in 24 hours."
            ),
        )
    except EmailDeliveryError as exc:
        logger.error(
            "Failed to send verification email to user_id=%s email=%s: %s", user_id, email, exc, exc_info=True
        )


def _issue_and_queue_verification_email(db: Session, user: User, background_tasks: BackgroundTasks) -> None:
    token = create_email_verification_token(db, user.id)
    background_tasks.add_task(_send_verification_email, user.id, user.email, token)


async def _send_password_reset_email(user_id: int, email: str, token: str) -> None:
    """Runs as a FastAPI BackgroundTask -- see _send_verification_email for
    why failures must be caught and logged here rather than left to
    propagate.
    """
    reset_url = f"{settings.frontend_base_url}/reset-password?token={token}"
    provider = get_email_provider()
    try:
        await provider.send(
            to=email,
            subject=TEXT_PASSWORD_RESET_SUBJECT,
            body=(
                "Click the link below to choose a new password:\n\n"
                f"{reset_url}\n\n"
                "This link expires in 1 hour. If you didn't request this, you can ignore this email."
            ),
        )
    except EmailDeliveryError as exc:
        logger.error(
            "Failed to send password reset email to user_id=%s email=%s: %s", user_id, email, exc, exc_info=True
        )


def _issue_and_queue_password_reset_email(db: Session, user: User, background_tasks: BackgroundTasks) -> None:
    token = create_password_reset_token(db, user.id)
    background_tasks.add_task(_send_password_reset_email, user.id, user.email, token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/signup", response_model=MessageResponse)
def signup(payload: UserSignup, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Same enumeration principle as /forgot-password: the caller must not be able to
    tell "email already registered" from "account created" by status, body, or shape.
    """
    generic_response = MessageResponse(message=TEXT_SIGNUP_GENERIC_MESSAGE)

    try:
        user = crud.create_user(
            db, email=payload.email, hashed_password=hash_password(payload.password), name=payload.name
        )
    except IntegrityError:
        db.rollback()
        return generic_response

    _issue_and_queue_verification_email(db, user, background_tasks)
    return generic_response


@router.get("/verify-email", response_model=MessageResponse)
def verify_email(token: str, db: Session = Depends(get_db)):
    try:
        token_row = verify_email_verification_token(db, token)
    except EmailVerificationTokenError as exc:
        logger.info("Email verification failed: %s", exc.reason)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification link")

    token_row.used_at = datetime.now(timezone.utc)
    user = db.query(User).filter(User.id == token_row.user_id).first()
    user.is_active = True
    db.commit()

    return MessageResponse(message="Email verified successfully")


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(
    payload: ResendVerificationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Resend a verification email when the account still needs one.

    The response stays the same in every case so people cannot tell whether
    the email exists, the account is already active, or a new email was sent.
    If the last verification email was sent too recently, this skips sending a
    new one but still returns the same generic success message.
    """
    user = crud.get_user_by_email(db, payload.email)

    generic_response = MessageResponse(
        message="If an account exists for that email and needs verification, a new email has been sent."
    )
    if user is None or user.is_active:
        return generic_response

    last_token = (
        db.query(EmailVerificationToken)
        .filter(EmailVerificationToken.user_id == user.id)
        .order_by(EmailVerificationToken.created_at.desc())
        .first()
    )
    if last_token is not None:
        elapsed_seconds = (datetime.now(timezone.utc) - last_token.created_at).total_seconds()
        if elapsed_seconds < EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS:
            return generic_response

    _issue_and_queue_verification_email(db, user, background_tasks)
    return generic_response


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(payload: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Send a password reset email when the account can use one.

    The reply is always the same so people cannot tell whether the email
    exists, belongs to an SSO-only account, or already has a reset email
    queued. If the last reset email was sent too recently, this skips sending
    a new one but still returns the same generic message.
    """
    generic_response = MessageResponse(message=TEXT_FORGOT_PASSWORD_GENERIC_MESSAGE)

    user = crud.get_user_by_email(db, payload.email)
    eligible = user is not None and not user.is_sso_user

    if not eligible:
        return generic_response

    cooldown_user_id = user.id if user is not None else -1
    last_token = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == cooldown_user_id)
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )

    if last_token is not None:
        elapsed_seconds = (datetime.now(timezone.utc) - last_token.created_at).total_seconds()
        if elapsed_seconds < PASSWORD_RESET_RESEND_COOLDOWN_SECONDS:
            return generic_response

    _issue_and_queue_password_reset_email(db, user, background_tasks)
    return generic_response


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a password with a valid, unused token."""
    try:
        token_row = verify_password_reset_token(db, payload.token)
    except PasswordResetTokenError as exc:
        logger.info("Password reset failed: %s", exc.reason)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset link")

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
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, payload.email)
    if user is None or user.hashed_password is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=TEXT_LOGIN_INVALID_CREDENTIALS)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TEXT_LOGIN_EMAIL_NOT_VERIFIED,
        )

    return Token(access_token=create_access_token(user.id))


@router.get("/google/login")
def google_login(db: Session = Depends(get_db)):
    state = create_oauth_state(db, purpose=GOOGLE_LOGIN_STATE_PURPOSE)
    return RedirectResponse(google_oauth.build_authorize_url(state))


@router.get("/google/callback")
def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    try:
        consume_oauth_state(db, token=state, expected_purpose=GOOGLE_LOGIN_STATE_PURPOSE)
    except OAuthStateError as exc:
        logger.info("Google login state validation failed: %s", exc.message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    try:
        id_token = google_oauth.exchange_code_for_id_token(code)
        claims = google_oauth.verify_google_id_token(id_token)
    except GoogleAuthError as exc:
        logger.info("Google login failed: %s", exc)
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

    access_token = create_access_token(user.id)
    # KNOWN, DEFERRED: the access token rides in the redirect URL, so it lands
    # in browser history/referrer headers/server logs. Deliberately not fixed
    # here -- the right shape (short-lived one-time exchange code the
    # frontend swaps for the real token, vs. setting it as an httpOnly
    # cookie directly) depends on how /oauth/callback ends up handling auth
    # state, which isn't built yet. Decide when that frontend work starts,
    # not now.
    return RedirectResponse(f"{settings.frontend_base_url}/oauth/callback?token={access_token}")
