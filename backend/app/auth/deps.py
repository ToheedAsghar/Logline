import hmac

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


def get_tracker_device(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> TrackerDevice:
    """Authenticates a local tracker daemon using a long-lived device token. Returns the authenticated TrackerDevice
    model. Uses constant-time comparison to verify the device secret token against timing attacks.
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
    if device is None or not hmac.compare_digest(device.token, secret):
        raise unauthorized

    return device


def get_tracker_user(
    device: TrackerDevice = Depends(get_tracker_device),
) -> User:
    """Convenience dependency returning the User owning the authenticated tracker device."""
    return device.user
