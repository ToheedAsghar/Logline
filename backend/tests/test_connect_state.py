"""Tests for the connect_state module (user_id binding for OAuth flows).

These tests focus on the signed envelope that wraps an OAuth state token to
bind it to a specific user. We test that the envelope can be created,
validated, and that tampering with it is correctly rejected. We use a real
test Postgres database (via docker-compose) for the inner OAuth state row,
but don't test signature validation itself -- that's covered by the core
oauth_state module's tests.
"""

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.config import settings
from app.core.oauth_state import OAuthState, OAuthStateError
from app.db.session import SessionLocal
from app.integrations.connect_state import CONNECT_STATE_SALT, consume_connect_state, create_connect_state
from app.integrations.models import IntegrationSource


def _delete_all_oauth_states(db) -> None:
    db.query(OAuthState).delete()
    db.commit()


@pytest.fixture
def db():
    session = SessionLocal()
    _delete_all_oauth_states(session)
    yield session
    _delete_all_oauth_states(session)
    session.close()


class TestCreateConnectState:
    def test_persists_an_inner_state_row_and_returns_a_token_carrying_user_id(self, db):
        token = create_connect_state(db, user_id=42, source=IntegrationSource.slack)

        assert db.query(OAuthState).count() == 1
        row = db.query(OAuthState).first()
        assert row.purpose == "slack_connect"
        assert row.used_at is None

        serializer = URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=CONNECT_STATE_SALT)
        payload = serializer.loads(token)
        assert payload["user_id"] == 42


class TestConsumeConnectStateHappyPath:
    def test_valid_unused_state_returns_user_id_and_marks_inner_state_used(self, db):
        token = create_connect_state(db, user_id=7, source=IntegrationSource.slack)

        user_id = consume_connect_state(db, token=token, expected_source=IntegrationSource.slack)

        assert user_id == 7
        row = db.query(OAuthState).first()
        assert row.used_at is not None


class TestConsumeConnectStateRejections:
    def test_rejects_tampered_outer_envelope(self, db):
        token = create_connect_state(db, user_id=1, source=IntegrationSource.slack)
        mid = len(token) // 2
        tampered = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1 :]

        with pytest.raises(OAuthStateError):
            consume_connect_state(db, token=tampered, expected_source=IntegrationSource.slack)

    def test_rejects_second_use_of_the_same_state(self, db):
        token = create_connect_state(db, user_id=3, source=IntegrationSource.slack)

        consume_connect_state(db, token=token, expected_source=IntegrationSource.slack)

        with pytest.raises(OAuthStateError):
            consume_connect_state(db, token=token, expected_source=IntegrationSource.slack)

    def test_rejects_source_mismatch(self, db):
        token = create_connect_state(db, user_id=4, source=IntegrationSource.github)

        with pytest.raises(OAuthStateError):
            consume_connect_state(db, token=token, expected_source=IntegrationSource.slack)

    def test_rejects_unrelated_signed_envelope_missing_expected_fields(self, db):
        """A validly-signed envelope from a *different* itsdangerous salt (or
        one built by hand without the expected keys) must be rejected, not
        crash with a KeyError -- proves the envelope's own shape is
        checked, not just its signature."""
        serializer = URLSafeTimedSerializer(settings.itsdangerous_secret_key, salt=CONNECT_STATE_SALT)
        malformed = serializer.dumps({"unexpected": "shape"})

        with pytest.raises(OAuthStateError):
            consume_connect_state(db, token=malformed, expected_source=IntegrationSource.slack)
