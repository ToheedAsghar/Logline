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


@pytest.fixture(autouse=True)
def reset_jwks_cache():
    """The in-process JWKS TTL cache is module-level state in google_oauth.py
    -- without a reset, whichever test runs first would seed it and every
    later test in this file (or others) would silently reuse that cached
    JWKS instead of exercising its own fake HTTP client.
    """
    google_oauth._jwks_cache["jwks"] = None
    google_oauth._jwks_cache["fetched_at"] = 0.0
    yield
    google_oauth._jwks_cache["jwks"] = None
    google_oauth._jwks_cache["fetched_at"] = 0.0


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

    def test_missing_sub_claim_rejected(self):
        """A validly-signed token without `sub` would otherwise crash the
        router at `claims["sub"]` with a raw KeyError -- Google always sends
        this in practice, but verify_google_id_token should still reject it
        cleanly as defense-in-depth, consistent with the email checks above.
        """
        claims = _base_claims()
        del claims["sub"]
        token = _sign(claims)

        with pytest.raises(GoogleAuthError, match="sub"):
            verify_google_id_token(token)


class _SpyJWKSResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _RaisingJWKSResponse:
    def raise_for_status(self) -> None:
        import httpx

        raise httpx.HTTPStatusError("503 Service Unavailable", request=None, response=None)


class _SpyHTTPXClient:
    """Records call count and returns whatever `next(responses)` yields,
    standing in for google_oauth.HTTPXClient across the JWKS fetch/caching
    tests below.
    """

    calls = 0
    response_factory = None  # set per-test: callable() -> response object

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False

    def get(self, url):
        type(self).calls += 1
        return type(self).response_factory()


@pytest.fixture
def spy_jwks_client(monkeypatch):
    _SpyHTTPXClient.calls = 0
    _SpyHTTPXClient.response_factory = lambda: _SpyJWKSResponse(_jwks())
    monkeypatch.setattr(google_oauth, "HTTPXClient", _SpyHTTPXClient)
    return _SpyHTTPXClient


class TestJWKSFetchFailure:
    def test_http_failure_surfaces_as_google_auth_error_not_raw_exception(self, spy_jwks_client):
        spy_jwks_client.response_factory = _RaisingJWKSResponse

        token = _sign(_base_claims())

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)

    def test_connection_failure_surfaces_as_google_auth_error(self, monkeypatch):
        import httpx

        class _BrokenHTTPXClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                raise httpx.ConnectError("connection refused", request=None)

        monkeypatch.setattr(google_oauth, "HTTPXClient", _BrokenHTTPXClient)
        token = _sign(_base_claims())

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)

    def test_malformed_json_response_surfaces_as_google_auth_error(self, monkeypatch):
        class _MalformedJSONResponse:
            def raise_for_status(self):
                pass

            def json(self):
                raise ValueError("Invalid JSON string")

        class _MalformedHTTPXClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                return _MalformedJSONResponse()

        monkeypatch.setattr(google_oauth, "HTTPXClient", _MalformedHTTPXClient)
        token = _sign(_base_claims())

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)


class TestJWKSTTLCaching:
    def test_second_login_within_ttl_does_not_refetch(self, spy_jwks_client):
        token = _sign(_base_claims())

        verify_google_id_token(token)
        verify_google_id_token(token)

        assert spy_jwks_client.calls == 1

    def test_expired_ttl_triggers_refetch(self, spy_jwks_client):
        token = _sign(_base_claims())

        verify_google_id_token(token)
        assert spy_jwks_client.calls == 1

        # Simulate the cached entry having aged past the TTL.
        google_oauth._jwks_cache["fetched_at"] -= google_oauth.JWKS_CACHE_TTL_SECONDS + 1

        verify_google_id_token(token)
        assert spy_jwks_client.calls == 2


class TestJWKSUnknownKidRefresh:
    def test_unknown_kid_triggers_exactly_one_refresh_then_succeeds(self, spy_jwks_client):
        # Seed the cache with a stale JWKS containing a *different* key than
        # the one the token below is actually signed with, standing in for
        # a real key rotation the cache hasn't caught up with yet.
        stale_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        stale_public = stale_key.as_dict(is_private=False)
        stale_public["kid"] = "stale-kid"
        google_oauth._jwks_cache["jwks"] = {"keys": [stale_public]}
        google_oauth._jwks_cache["fetched_at"] = time.monotonic()

        token = _sign(_base_claims())  # signed with _KEY / _KID, not the stale one

        claims = verify_google_id_token(token)

        assert claims["sub"] == "google-sub-crypto-test"
        assert spy_jwks_client.calls == 1

    def test_still_unknown_kid_after_refresh_rejected_cleanly(self, spy_jwks_client):
        # Cache is pre-seeded with a stale key (so the initial lookup is a
        # cache hit, not a fetch), and the "server" JWKS the refresh fetches
        # also lacks the token's kid -- proves the one-shot retry doesn't
        # loop and still fails as a clean GoogleAuthError, not a raw
        # ValueError/500 from Authlib's key-set lookup.
        stale_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        stale_public = stale_key.as_dict(is_private=False)
        stale_public["kid"] = "stale-kid"
        google_oauth._jwks_cache["jwks"] = {"keys": [stale_public]}
        google_oauth._jwks_cache["fetched_at"] = time.monotonic()

        other_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        other_public = other_key.as_dict(is_private=False)
        other_public["kid"] = "totally-unrelated-kid"
        spy_jwks_client.response_factory = lambda: _SpyJWKSResponse({"keys": [other_public]})

        token = _sign(_base_claims())  # signed with _KEY / _KID

        with pytest.raises(GoogleAuthError):
            verify_google_id_token(token)

        assert spy_jwks_client.calls == 1
