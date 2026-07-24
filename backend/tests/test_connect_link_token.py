"""Tests for creating and using one-time passes (connect-link tokens).

These tests confirm that:
- Creating a pass stores a database row and returns a valid, signed token.
- Redeeming a valid, unused pass for the right provider returns the user ID.
- A pass can only be used once (second use is rejected).
- A pass rejects tampering, expiry, wrong provider, or missing row.
- A pass's single-use guarantee holds across separate database connections
  (the write from the first use is durable before the second attempt reads it).

The tests use a real Postgres database (not mocks) because the point is to
verify that the database locking and row writes work correctly.
"""

import threading

import pytest

from app.auth.models import User
from app.db.session import SessionLocal
from app.integrations.connect_link_token import (
    ConnectLinkTokenError, consume_connect_link_token, create_connect_link_token,
)
from app.integrations.models import ConnectLinkToken, IntegrationSource

TEST_EMAIL = "connect-link-token-test@example.com"


@pytest.fixture
def real_db_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        db.query(ConnectLinkToken).filter(ConnectLinkToken.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(ConnectLinkToken).filter(ConnectLinkToken.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestCreateConnectLinkToken:
    def test_creates_a_token_row(self, real_db_user):
        db = SessionLocal()
        try:
            create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)

            row = db.query(ConnectLinkToken).filter(ConnectLinkToken.user_id == real_db_user).first()
            assert row is not None
            assert row.source == "slack"
            assert row.used_at is None
        finally:
            db.close()

    def test_returns_a_string_token(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)
            assert isinstance(token, str)
            assert token != ""
        finally:
            db.close()


class TestConsumeConnectLinkToken:
    def test_valid_token_resolves_to_the_issuing_user(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)

            user_id = consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)

            assert user_id == real_db_user
        finally:
            db.close()

    def test_marks_the_row_used_on_success(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)
            consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)

            row = db.query(ConnectLinkToken).filter(ConnectLinkToken.user_id == real_db_user).first()
            assert row.used_at is not None
        finally:
            db.close()

    def test_tampered_token_is_rejected(self, real_db_user):
        """Tampering with any character in the token payload or signature must
        cause token consumption to be rejected with reason='tampered'.

        We modify a character in the middle of the token string (rather than
        the last character) because flipping the final character of a base64-encoded
        string can fall into unused padding bits and fail to alter the decoded
        bytes, creating a flaky test that intermittently passes without actual tampering.
        """
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)
            mid = len(token) // 2
            tampered = token[:mid] + ("a" if token[mid] != "a" else "b") + token[mid + 1 :]

            with pytest.raises(ConnectLinkTokenError) as exc_info:
                consume_connect_link_token(db, token=tampered, expected_source=IntegrationSource.slack)
            assert exc_info.value.reason == "tampered"
        finally:
            db.close()

    def test_garbage_token_is_rejected_as_tampered(self, real_db_user):
        db = SessionLocal()
        try:
            with pytest.raises(ConnectLinkTokenError) as exc_info:
                consume_connect_link_token(db, token="not-a-real-token", expected_source=IntegrationSource.slack)
            assert exc_info.value.reason == "tampered"
        finally:
            db.close()

    def test_expired_token_is_rejected(self, real_db_user, monkeypatch):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)

            # -1 forces immediate expiry: itsdangerous's timestamp resolution
            # is whole seconds, so age is 0 (not > 0) within the same
            # second -- max_age must be negative to guarantee age > max_age.
            monkeypatch.setattr("app.integrations.connect_link_token.CONNECT_LINK_TOKEN_TTL_SECONDS", -1)

            with pytest.raises(ConnectLinkTokenError) as exc_info:
                consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)
            assert exc_info.value.reason == "expired"
        finally:
            db.close()

    def test_already_used_token_is_rejected(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)
            consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)

            with pytest.raises(ConnectLinkTokenError) as exc_info:
                consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)
            assert exc_info.value.reason == "already_used"
        finally:
            db.close()

    def test_nonexistent_row_is_rejected_as_not_found(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)
            db.query(ConnectLinkToken).filter(ConnectLinkToken.user_id == real_db_user).delete()
            db.commit()

            with pytest.raises(ConnectLinkTokenError) as exc_info:
                consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)
            assert exc_info.value.reason == "not_found"
        finally:
            db.close()

    def test_source_mismatch_is_rejected(self, real_db_user):
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.github)

            with pytest.raises(ConnectLinkTokenError) as exc_info:
                consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)
            assert exc_info.value.reason == "source_mismatch"
        finally:
            db.close()

    def test_second_use_after_first_success_leaves_row_used_at_set(self, real_db_user):
        """Belt-and-suspenders check on top of test_already_used_token_is_rejected:
        confirms the used_at write from the first consume is durably committed
        (not just held in that session), by reading it back from a fresh
        session before the second consume attempt.
        """
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)
            consume_connect_link_token(db, token=token, expected_source=IntegrationSource.slack)
        finally:
            db.close()

        verify_db = SessionLocal()
        try:
            row = verify_db.query(ConnectLinkToken).filter(ConnectLinkToken.user_id == real_db_user).first()
            assert row.used_at is not None
        finally:
            verify_db.close()

        replay_db = SessionLocal()
        try:
            with pytest.raises(ConnectLinkTokenError) as exc_info:
                consume_connect_link_token(replay_db, token=token, expected_source=IntegrationSource.slack)
            assert exc_info.value.reason == "already_used"
        finally:
            replay_db.close()


class TestConsumeConnectLinkTokenConcurrency:
    def test_concurrent_double_consume_only_one_succeeds(self, real_db_user):
        """Spin up two threads that both call consume_connect_link_token on the
        SAME token concurrently, each using its own separate SessionLocal() connection.

        The row-level lock (with_for_update) inside consume_connect_link_token
        guarantees atomicity: exactly one thread must succeed and return the user ID,
        while the other thread must raise ConnectLinkTokenError with reason='already_used'.
        This serves as a regression tripwire against replacing row locks with unsafe
        check-then-commit patterns.
        """
        db = SessionLocal()
        try:
            token = create_connect_link_token(db, user_id=real_db_user, source=IntegrationSource.slack)
        finally:
            db.close()

        results = {}

        def attempt(thread_name: str) -> None:
            thread_db = SessionLocal()
            try:
                try:
                    res_user_id = consume_connect_link_token(
                        thread_db, token=token, expected_source=IntegrationSource.slack
                    )
                    results[thread_name] = ("success", res_user_id)
                except ConnectLinkTokenError as exc:
                    results[thread_name] = ("error", exc.reason)
            finally:
                thread_db.close()

        t1 = threading.Thread(target=attempt, args=("thread_1",))
        t2 = threading.Thread(target=attempt, args=("thread_2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [v for v in results.values() if v[0] == "success"]
        failures = [v for v in results.values() if v[0] == "error"]

        assert len(successes) == 1, f"Expected exactly 1 success, got: {results}"
        assert len(failures) == 1, f"Expected exactly 1 error, got: {results}"
        assert successes[0][1] == real_db_user
        assert failures[0][1] == "already_used"
