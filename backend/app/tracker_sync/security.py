"""Device-token generation and hashing for tracker enrollment.

Tokens are stored as an unsalted SHA-256 hash rather than bcrypt: 32 bytes of `secrets` entropy needs no work
factor, and a deterministic hash is what lets authentication find the device by one indexed lookup.
"""

import hashlib
import secrets

DEVICE_TOKEN_BYTES = 32


def generate_device_token() -> str:
    """Returns a fresh URL-safe token. The caller must return this to the enrolling client exactly once -- only its
    hash is persisted, so it can never be recovered afterwards."""
    return secrets.token_urlsafe(DEVICE_TOKEN_BYTES)


def hash_device_token(token: str) -> str:
    """Hex SHA-256 of the presented token, matching what `TrackerDevice.token_hash` stores."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
