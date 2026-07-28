"""
Tests for the remote_events table (app/matching/models.py) against the real
Postgres database: the (user_id, source, external_id) unique constraint that
makes re-fetching the same remote event idempotent *per user* without
colliding across different users' data, and that `source` reuses the real
`integration_source` Postgres enum (app/models/integration.py) rather than
a plain string.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import DataError, IntegrityError

from app.db.session import SessionLocal
from app.matching.models import RemoteEvent
from app.auth.models import User

TEST_EMAIL = "remote-events-table-test@example.com"
OTHER_TEST_EMAIL = "remote-events-table-test-other-user@example.com"


@pytest.fixture
def real_db_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        db.query(RemoteEvent).filter(RemoteEvent.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(RemoteEvent).filter(RemoteEvent.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def other_real_db_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == OTHER_TEST_EMAIL).first()
        if user is None:
            user = User(email=OTHER_TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        db.query(RemoteEvent).filter(RemoteEvent.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(RemoteEvent).filter(RemoteEvent.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


def _event(user_id: int, source: str, external_id: str, **overrides) -> RemoteEvent:
    fields = dict(
        user_id=user_id,
        source=source,
        event_type="commit",
        external_id=external_id,
        occurred_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        raw_data={"sha": external_id},
    )
    fields.update(overrides)
    return RemoteEvent(**fields)


class TestUniqueConstraint:
    def test_duplicate_user_source_and_external_id_is_rejected(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(_event(real_db_user, "github", "sha-dup"))
            db.commit()

            db.add(_event(real_db_user, "github", "sha-dup"))
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.rollback()
            db.close()

    def test_same_external_id_different_source_is_allowed(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(_event(real_db_user, "github", "shared-id"))
            db.add(_event(real_db_user, "jira", "shared-id"))
            db.commit()

            rows = db.query(RemoteEvent).filter(RemoteEvent.user_id == real_db_user).all()
            assert len(rows) == 2
        finally:
            db.close()

    def test_same_source_and_external_id_different_users_is_allowed(self, real_db_user, other_real_db_user):
        """The direct regression test for this constraint: two different
        Logline users can each have their own remote event for the same
        source + external_id (e.g. two users on the same GitHub repo, or
        two Jira Cloud sites whose transition IDs happen to collide) --
        this must succeed for both, never collide, since external_id is
        only unique *within* a source, not globally across users."""
        db = SessionLocal()
        try:
            db.add(_event(real_db_user, "github", "shared-across-users"))
            db.add(_event(other_real_db_user, "github", "shared-across-users"))
            db.commit()

            rows = (
                db.query(RemoteEvent)
                .filter(RemoteEvent.external_id == "shared-across-users")
                .all()
            )
            assert len(rows) == 2
            assert {row.user_id for row in rows} == {real_db_user, other_real_db_user}
        finally:
            db.close()


class TestSourceIsIntegrationEnum:
    def test_valid_source_value_is_accepted(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(_event(real_db_user, "github", "enum-valid-1"))
            db.commit()

            row = db.query(RemoteEvent).filter(RemoteEvent.user_id == real_db_user).first()
            assert row.source == "github"
        finally:
            db.close()

    def test_arbitrary_source_string_is_rejected(self, real_db_user):
        """`source` reuses the real `integration_source` Postgres enum type
        (shared with Integration.source), so a value outside its fixed set
        (github/slack/jira/calendar) is rejected at the database level."""
        db = SessionLocal()
        try:
            db.add(_event(real_db_user, "not_a_real_integration_source", "arbitrary-1"))
            with pytest.raises(DataError):
                db.commit()
        finally:
            db.rollback()
            db.close()
