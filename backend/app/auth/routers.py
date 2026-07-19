import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import crud
from app.auth.constants import (
    EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS, TEXT_LOGIN_EMAIL_NOT_VERIFIED, TEXT_LOGIN_INVALID_CREDENTIALS,
)
from app.auth.deps import get_current_user
from app.auth.models import EmailVerificationToken, User
from app.auth.schemas import MessageResponse, ResendVerificationRequest, Token, UserLogin, UserResponse, UserSignup
from app.auth.security import (
    EmailVerificationTokenError, create_access_token, create_email_verification_token, hash_password,
    verify_email_verification_token, verify_password,
)
from app.config import settings
from app.core.email import get_email_provider
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger(__name__)


async def _send_verification_email(user_id: int, email: str, token: str) -> None:
    verify_url = f"{settings.frontend_base_url}/verify-email?token={token}"
    provider = get_email_provider()
    await provider.send(
        to=email,
        subject="Verify your Logline email",
        body=(
            "Click the link below to verify your email address:\n\n"
            f"{verify_url}\n\n"
            "This link expires in 24 hours."
        ),
    )


def _issue_and_queue_verification_email(db: Session, user: User, background_tasks: BackgroundTasks) -> None:
    token = create_email_verification_token(db, user.id)
    background_tasks.add_task(_send_verification_email, user.id, user.email, token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserSignup, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        user = crud.create_user(
            db, email=payload.email, hashed_password=hash_password(payload.password), name=payload.name
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    _issue_and_queue_verification_email(db, user, background_tasks)
    return user


@router.get("/verify-email", response_model=MessageResponse)
def verify_email(token: str, db: Session = Depends(get_db)):
    try:
        token_row = verify_email_verification_token(db, token)
    except EmailVerificationTokenError as exc:
        logger.info("Email verification failed: %s", exc.reason)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification link"
        )

    token_row.used_at = datetime.now(timezone.utc)
    user = db.query(User).filter(User.id == token_row.user_id).first()
    user.is_active = True
    db.commit()

    return MessageResponse(message="Email verified successfully")


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(
    payload: ResendVerificationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
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
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="A verification email was already sent recently. Please wait before requesting another.",
            )

    _issue_and_queue_verification_email(db, user, background_tasks)
    return generic_response


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=TEXT_LOGIN_INVALID_CREDENTIALS)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TEXT_LOGIN_EMAIL_NOT_VERIFIED,
        )

    return Token(access_token=create_access_token(user.id))
