"""Regression tests for CodeRabbit #5 (auth/schemas.py): passwords must be
rejected before hashing if empty or unbounded in length. PASSWORD_MIN_LENGTH
and PASSWORD_MAX_LENGTH (app/auth/constants.py) are enforced identically on
both UserSignup and UserLogin via pydantic Field constraints.
"""

import pytest
from pydantic import ValidationError

from app.auth.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.auth.schemas import UserLogin, UserSignup
from app.auth.security import hash_password, verify_password


@pytest.mark.parametrize("schema", [UserSignup, UserLogin])
class TestPasswordLengthValidation:
    def _payload(self, schema, password: str) -> dict:
        payload = {"email": "user@example.com", "password": password}
        if schema is UserSignup:
            payload["name"] = "Test User"
        return payload

    def test_empty_password_rejected(self, schema):
        with pytest.raises(ValidationError):
            schema(**self._payload(schema, ""))

    def test_too_short_password_rejected(self, schema):
        with pytest.raises(ValidationError):
            schema(**self._payload(schema, "a" * (PASSWORD_MIN_LENGTH - 1)))

    def test_too_long_password_rejected(self, schema):
        with pytest.raises(ValidationError):
            schema(**self._payload(schema, "a" * (PASSWORD_MAX_LENGTH + 1)))

    def test_minimum_length_password_accepted(self, schema):
        instance = schema(**self._payload(schema, "a" * PASSWORD_MIN_LENGTH))
        assert instance.password == "a" * PASSWORD_MIN_LENGTH

    def test_maximum_length_password_accepted(self, schema):
        instance = schema(**self._payload(schema, "a" * PASSWORD_MAX_LENGTH))
        assert instance.password == "a" * PASSWORD_MAX_LENGTH

    def test_ordinary_password_accepted(self, schema):
        instance = schema(**self._payload(schema, "correct-horse-battery"))
        assert instance.password == "correct-horse-battery"


class TestHashPasswordHandlesFullLengthAndMultiByteInput:
    """Regression test for the bcrypt 5.x crash: bcrypt raises ValueError on
    any input whose UTF-8 byte length exceeds 72, rather than truncating.
    PASSWORD_MAX_LENGTH=128 is a *character* count, so a schema-valid
    password can still overflow bcrypt's 72-byte limit -- either by being
    a long all-ASCII password (128 bytes) or, well under 128 characters,
    by containing multi-byte characters (emoji here, at 4 bytes each).
    hash_password/verify_password pre-hash with SHA-256 to a fixed-size
    input, so both cases must succeed without raising.
    """

    def test_maximum_length_password_hashes_and_verifies(self):
        password = "a" * PASSWORD_MAX_LENGTH
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True
        assert verify_password("b" * PASSWORD_MAX_LENGTH, hashed) is False

    def test_multi_byte_emoji_password_hashes_and_verifies(self):
        # 30 emoji * 4 bytes/char (UTF-8) = 120 bytes, well over bcrypt's
        # 72-byte ceiling, while only 30 characters -- comfortably under
        # PASSWORD_MAX_LENGTH -- proving this is a byte-length bug, not a
        # character-length one.
        password = "\U0001F600" * 30
        assert len(password) < PASSWORD_MAX_LENGTH
        assert len(password.encode()) > 72

        hashed = hash_password(password)

        assert verify_password(password, hashed) is True
        assert verify_password("\U0001F601" * 30, hashed) is False
