import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.security import decode_access_token
from app.db.session import get_db
from app.tracker_sync.models import TrackerDevice

_bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise unauthorized

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise unauthorized

    return user


def get_tracker_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Authenticates a local tracker daemon using a long-lived device token.
    
    This is used by the tracker sync endpoint instead of the standard JWT-based
    `get_current_user` since the tracker runs unattended and doesn't have a UI to
    complete a web login flow.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid tracker device token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        device_id_str, secret = credentials.credentials.split(":", 1)
    except ValueError:
        raise unauthorized

    device = db.query(TrackerDevice).filter(TrackerDevice.device_id == device_id_str).first()
    if device is None or device.token != secret:
        raise unauthorized

    user = db.query(User).filter(User.id == device.user_id).first()
    if user is None:
        raise unauthorized

    return user
