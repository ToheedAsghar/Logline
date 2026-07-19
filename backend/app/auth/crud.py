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
