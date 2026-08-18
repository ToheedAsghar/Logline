import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.constants import TEXT_UNAUTHORIZED
from app.auth.models import User
from app.auth.security import decode_access_token
from app.db.session import get_db
from app.tracker_sync import crud
from app.tracker_sync.constants import INVALID_DEVICE_TOKEN_ERROR_MSG
from app.tracker_sync.models import TrackerDevice

_bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=TEXT_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise unauthorized

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise unauthorized

    return user


def get_tracker_device(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> TrackerDevice:
    """Authenticates a local tracker daemon by the hash of its opaque device token.

    An unknown token, a revoked device, and a device left without a hash all raise the same 401, so the client
    learns nothing about which it hit.
    """
    device = crud.get_device_by_token(db, credentials.credentials)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_DEVICE_TOKEN_ERROR_MSG,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return device


def get_tracker_user(
    device: TrackerDevice = Depends(get_tracker_device),
) -> User:
    """Convenience dependency returning the User owning the authenticated tracker device."""
    return device.user
