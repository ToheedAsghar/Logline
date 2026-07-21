"""Google OAuth: authorize-URL construction, code exchange, and ID token
verification. All Google-specific wire logic lives here so
app/auth/routers.py only deals in claims/tokens, not HTTP details.
"""

from urllib.parse import urlencode

from authlib.integrations.httpx_client import OAuth2Client
from authlib.jose import jwt as jose_jwt
from authlib.jose.errors import JoseError
from httpx import Client as HTTPXClient

from app.config import settings

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
GOOGLE_SCOPES = ["openid", "email", "profile"]
TEXT_GOOGLE_MISSING_ID_TOKEN = "Google's token response did not include an id_token"
TEXT_GOOGLE_EMAIL_NOT_VERIFIED = "Google account email is not verified"
TEXT_GOOGLE_MISSING_EMAIL_CLAIM = "Google ID token did not include an email claim"


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
    with HTTPXClient(timeout=10) as http_client:
        response = http_client.get(GOOGLE_JWKS_URL)
        response.raise_for_status()
        return response.json()


def verify_google_id_token(id_token_str: str) -> dict:
    """Verify signature, issuer, audience, and expiry via Authlib against
    Google's published JWKS, then require `email_verified` to be true.

    Google's `email_verified` claim must be checked and required true before
    trusting the email for either linking or fresh signup -- a validly
    *signed* token is only proof the claims came from Google, not proof
    Google itself vouches for the email address being genuine.
    """
    jwks = _fetch_jwks()

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
    except JoseError as exc:
        raise GoogleAuthError(f"ID token validation failed: {exc}") from exc

    if not claims.get("email_verified"):
        raise GoogleAuthError(TEXT_GOOGLE_EMAIL_NOT_VERIFIED)
    if not claims.get("email"):
        raise GoogleAuthError(TEXT_GOOGLE_MISSING_EMAIL_CLAIM)

    return dict(claims)
