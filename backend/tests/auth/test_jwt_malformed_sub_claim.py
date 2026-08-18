"""Regression test for CodeRabbit #6 (auth/security.py + auth/deps.py): a JWT
with a valid signature/expiry but a missing or non-numeric `sub` claim must
resolve to a 401 through get_current_user, not an unhandled KeyError/ValueError
surfacing as a 500. decode_access_token now normalizes both failure modes into
jwt.InvalidTokenError, a jwt.PyJWTError subclass get_current_user already
catches.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.deps import get_current_user
from app.auth.security import decode_access_token
from app.config import settings


def _encode(payload: dict) -> str:
    full_payload = {"exp": datetime.now(timezone.utc) + timedelta(minutes=5), **payload}
    return jwt.encode(full_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class TestDecodeAccessTokenRejectsMalformedSubClaim:
    def test_missing_sub_claim_raises_pyjwt_error(self):
        token = _encode({})
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(token)

    def test_non_numeric_sub_claim_raises_pyjwt_error(self):
        token = _encode({"sub": "not-a-user-id"})
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(token)

    def test_valid_numeric_sub_claim_decodes(self):
        token = _encode({"sub": "42"})
        assert decode_access_token(token) == 42


class TestGetCurrentUserReturns401NotServerError:
    def _credentials(self, token: str) -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def test_missing_sub_claim_produces_401(self):
        token = _encode({})
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=self._credentials(token), db=None)
        assert exc_info.value.status_code == 401

    def test_non_numeric_sub_claim_produces_401(self):
        token = _encode({"sub": "not-a-user-id"})
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=self._credentials(token), db=None)
        assert exc_info.value.status_code == 401
