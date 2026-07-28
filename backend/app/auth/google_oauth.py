"""Google OAuth: authorize-URL construction, code exchange, and ID token
verification. All Google-specific wire logic lives here so
app/auth/routers.py only deals in claims/tokens, not HTTP details.
"""

import base64
import json
import time
from threading import Lock
from urllib.parse import urlencode

from authlib.integrations.httpx_client import OAuth2Client
from authlib.jose import jwt as jose_jwt
from authlib.jose.errors import JoseError
from httpx import Client as HTTPXClient
from httpx import HTTPError

from app.auth.constants import (
    GOOGLE_AUTHORIZE_URL, GOOGLE_ISSUERS, GOOGLE_JWKS_URL, GOOGLE_SCOPES, GOOGLE_TOKEN_URL,
    TEXT_GOOGLE_EMAIL_NOT_VERIFIED, TEXT_GOOGLE_MISSING_EMAIL_CLAIM, TEXT_GOOGLE_MISSING_ID_TOKEN,
    TEXT_GOOGLE_MISSING_SUB_CLAIM,
)
from app.config import settings

JWKS_CACHE_TTL_SECONDS = 60 * 60  # Google's signing keys rotate infrequently.

_jwks_cache: dict = {"jwks": None, "fetched_at": 0.0}
_jwks_cache_lock = Lock()


class GoogleAuthError(Exception):
    """Raised when code exchange or ID token verification fails."""


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_id_token(code: str) -> str:
    """Exchange an authorization code for tokens via Authlib, returning the
    raw (still-unverified) id_token string. Callers must run this through
    verify_google_id_token before trusting anything in it.
    """
    client = OAuth2Client(client_id=settings.google_client_id, client_secret=settings.google_client_secret)
    try:
        token = client.fetch_token(
            GOOGLE_TOKEN_URL,
            code=code,
            grant_type="authorization_code",
            redirect_uri=settings.google_redirect_uri,
        )
    except Exception as exc:
        raise GoogleAuthError(f"Failed to exchange authorization code: {exc}") from exc

    id_token = token.get("id_token")
    if not id_token:
        raise GoogleAuthError(TEXT_GOOGLE_MISSING_ID_TOKEN)
    return id_token


def _fetch_jwks() -> dict:
    try:
        with HTTPXClient(timeout=10) as http_client:
            response = http_client.get(GOOGLE_JWKS_URL)
            response.raise_for_status()
            return response.json()
    except (HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise GoogleAuthError(f"Failed to fetch Google's signing keys: {exc}") from exc


def _get_jwks(*, force_refresh: bool = False) -> dict:
    """In-process TTL cache for Google's JWKS. `force_refresh` bypasses a
    fresh cache entry -- used by verify_google_id_token when a token's `kid`
    isn't among the cached keys, in case of an actual key rotation.
    """
    with _jwks_cache_lock:
        cached = _jwks_cache["jwks"]
        is_fresh = cached is not None and (time.monotonic() - _jwks_cache["fetched_at"]) < JWKS_CACHE_TTL_SECONDS
        if cached is not None and is_fresh and not force_refresh:
            return cached

    jwks = _fetch_jwks()
    with _jwks_cache_lock:
        _jwks_cache["jwks"] = jwks
        _jwks_cache["fetched_at"] = time.monotonic()
    return jwks


def _extract_kid(id_token_str: str) -> str | None:
    """Best-effort read of the unverified JWT header's `kid`. Used only to
    decide whether the JWKS cache needs a refresh -- the actual signature
    check still happens against the real (possibly refreshed) key set, so a
    malformed header here just falls through to a normal JoseError below.
    """
    try:
        header_b64 = id_token_str.split(".", 1)[0]
        padded = header_b64 + "=" * (-len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(padded))
        return header.get("kid")
    except Exception:
        return None


def _jwks_has_kid(jwks: dict, kid: str) -> bool:
    return any(key.get("kid") == kid for key in jwks.get("keys", []))


def verify_google_id_token(id_token_str: str) -> dict:
    """Verify signature, issuer, audience, and expiry via Authlib against
    Google's published JWKS, then require `email_verified` to be true.

    Google's `email_verified` claim must be checked and required true before
    trusting the email for either linking or fresh signup -- a validly
    *signed* token is only proof the claims came from Google, not proof
    Google itself vouches for the email address being genuine.
    """
    jwks = _get_jwks()

    kid = _extract_kid(id_token_str)
    if kid is not None and not _jwks_has_kid(jwks, kid):
        jwks = _get_jwks(force_refresh=True)

    try:
        claims = jose_jwt.decode(
            id_token_str,
            jwks,
            claims_options={
                "iss": {"essential": True, "values": GOOGLE_ISSUERS},
                "aud": {"essential": True, "value": settings.google_client_id},
            },
        )
        claims.validate()
    except (JoseError, ValueError) as exc:
        # Authlib raises a plain ValueError (not JoseError) for a kid that
        # still isn't in the JWKS after the refresh above -- e.g. a forged
        # kid, or a real rotation to a key our one retry didn't catch.
        raise GoogleAuthError(f"ID token validation failed: {exc}") from exc

    if not claims.get("email_verified"):
        raise GoogleAuthError(TEXT_GOOGLE_EMAIL_NOT_VERIFIED)
    if not claims.get("email"):
        raise GoogleAuthError(TEXT_GOOGLE_MISSING_EMAIL_CLAIM)
    if not claims.get("sub"):
        raise GoogleAuthError(TEXT_GOOGLE_MISSING_SUB_CLAIM)

    return dict(claims)
