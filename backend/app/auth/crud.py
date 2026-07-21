from sqlalchemy.orm import Session

from app.auth.models import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, *, email: str, hashed_password: str, name: str | None) -> User:
    user = User(email=normalize_email(email), hashed_password=hashed_password, name=name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == normalize_email(email)).first()


def get_user_by_google_id(db: Session, google_user_id: str) -> User | None:
    return db.query(User).filter(User.google_user_id == google_user_id).first()


def create_google_user(db: Session, *, email: str, google_user_id: str, name: str | None) -> User:
    """Fresh signup via Google: no password, active and SSO-linked immediately
    since Google's verified email is trustworthy proof.
    """
    user = User(
        email=normalize_email(email),
        hashed_password=None,
        name=name,
        is_active=True,
        is_sso_user=True,
        google_user_id=google_user_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def link_google_account(db: Session, user: User, *, google_user_id: str) -> User:
    """Bootstrap-link a Google login to an existing password account matched
    by email. Activates the account unconditionally -- Google's verified
    email is trustworthy proof, the same reasoning already applied to fresh
    SSO signups, so an existing-but-unverified account gets activated here too.
    """
    user.google_user_id = google_user_id
    user.is_sso_user = True
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user
