"""Direct tests for app/auth/google_oauth.py::verify_google_id_token.

Google's JWKS endpoint is faked (monkeypatched httpx client) but the actual
Authlib signature/claims verification runs for real against a self-signed
RSA key, so these tests prove the real cryptographic checks reject a
tampered signature, wrong audience/issuer, expiry, and an unverified email --
not just that the router maps a raised error to a 400. No live Google OAuth
flow is exercised (that's a deliberate separate step once this is reviewed).

No DB involved -- verify_google_id_token takes no Session.
"""
import time

import pytest
from authlib.jose import JsonWebKey
from authlib.jose import jwt as jose_jwt

from app.auth import google_oauth
from app.auth.google_oauth import GoogleAuthError, verify_google_id_token
from app.config import settings

_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True)
_KID = "test-kid"


def _jwks() -> dict:
    public = _KEY.as_dict(is_private=False)
    public["kid"] = _KID
    return {"keys": [public]}


def _sign(claims: dict) -> str:
    private = _KEY.as_dict(is_private=True)
    private["kid"] = _KID
    header = {"alg": "RS256", "kid": _KID}
    token = jose_jwt.encode(header, claims, private)
    return token.decode() if isinstance(token, bytes) else token


def _base_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": settings.google_client_id,
        "sub": "google-sub-crypto-test",
        "email": "crypto-test@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return claims


class _FakeJWKSResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return _jwks()


class _FakeHTTPXClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False

    def get(self, url):
        return _FakeJWKSResponse()


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    monkeypatch.setattr(google_oauth, "HTTPXClient", _FakeHTTPXClient)


class TestVerifyGoogleIdToken:
    def test_valid_token_returns_claims(self):
        token = _sign(_base_claims())

        claims = verify_google_id_token(token)

        assert claims["sub"] == "google-sub-crypto-test"
        assert claims["email"] == "crypto-test@example.com"
        assert claims["email_verified"] is True

    def test_tampered_signature_rejected(self):
        token = _sign(_base_claims())
        tampered = token[:-4] + ("XXXX" if not token.endswith("XXXX") else "YYYY")

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(tampered)

    def test_expired_token_rejected(self):
        now = int(time.time())
        token = _sign(_base_claims(iat=now - 7200, exp=now - 3600))

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)

    def test_wrong_audience_rejected(self):
        token = _sign(_base_claims(aud="not-our-client-id"))

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)

    def test_wrong_issuer_rejected(self):
        token = _sign(_base_claims(iss="https://evil.example.com"))

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)

    def test_email_not_verified_rejected(self):
        token = _sign(_base_claims(email_verified=False))

        with pytest.raises(GoogleAuthError, match="not verified"):
            verify_google_id_token(token)

    def test_missing_email_claim_rejected(self):
        claims = _base_claims()
        del claims["email"]
        token = _sign(claims)

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)
