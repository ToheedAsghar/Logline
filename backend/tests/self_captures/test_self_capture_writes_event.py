"""
Regression test for the self-capture -> Event fix (app/self_captures/routers.py).

Previously POST /self_captures only wrote to the self_captures table. Nothing
marked that time range as "covered" in a way gap-detection (flag_gap, which
only ever reads the `events` table) could see, so a gap filled via
self-capture would reappear after a refetch. `create_self_capture` now also
writes a corresponding Event row (source="self_capture", confidence="proven")
using the self-capture's own timestamp and text.

This hits the real test Postgres database (docker-compose, `logline_postgres`
-- see backend/CLAUDE.md), same pattern as
TestDatabaseConstraintRejectsBypassedDuplicate in test_write_event_dedup.py,
because the fix's whole point is a real second row landing in a real table --
a mocked session wouldn't prove that. No real LLM/MCP calls are made.
"""

from datetime import datetime, timezone

import pytest

from app.auth.models import User
from app.db.session import SessionLocal
from app.self_captures.models import SelfCapture
from app.self_captures.routers import create_self_capture
from app.self_captures.schemas import SelfCaptureCreate
from app.timeline.models import ConfidenceLevel, Event

TEST_EMAIL = "self-capture-writes-event-test@example.com"


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
        db.query(SelfCapture).filter(SelfCapture.user_id == user_id).delete()
        db.query(Event).filter(Event.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(SelfCapture).filter(SelfCapture.user_id == user_id).delete()
        db.query(Event).filter(Event.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestCreateSelfCaptureAlsoWritesEvent:
    def test_self_capture_row_and_event_row_are_both_created(self, real_db_user):
        db = SessionLocal()
        try:
            current_user = db.query(User).filter(User.id == real_db_user).first()
            timestamp = datetime(2026, 7, 7, 14, 30, tzinfo=timezone.utc)
            payload = SelfCaptureCreate(text="Fixed the flaky CI job.", timestamp=timestamp)

            response = create_self_capture(payload, current_user=current_user, db=db)

            assert response.id is not None

            self_capture_row = db.query(SelfCapture).filter(SelfCapture.id == response.id).first()
            assert self_capture_row is not None
            assert self_capture_row.text == "Fixed the flaky CI job."
            assert self_capture_row.timestamp == timestamp

            event_row = (
                db.query(Event)
                .filter(Event.user_id == real_db_user, Event.source == "self_capture")
                .first()
            )
            assert event_row is not None
            assert event_row.confidence == ConfidenceLevel.proven
            assert event_row.timestamp == timestamp
            assert event_row.event_metadata["self_capture_id"] == self_capture_row.id
            assert event_row.event_metadata["text"] == "Fixed the flaky CI job."
        finally:
            db.close()

    def test_linked_gap_id_is_carried_through_to_event_metadata(self, real_db_user):
        db = SessionLocal()
        try:
            current_user = db.query(User).filter(User.id == real_db_user).first()

            # A pre-existing "gap" event to link against (linked_gap_id is a
            # real FK to events.id).
            gap_event = Event(
                user_id=real_db_user,
                source="calendar",
                type="gap",
                timestamp=datetime(2026, 7, 7, 13, 0, tzinfo=timezone.utc),
                confidence=ConfidenceLevel.gap,
            )
            db.add(gap_event)
            db.commit()
            db.refresh(gap_event)

            timestamp = datetime(2026, 7, 7, 13, 15, tzinfo=timezone.utc)
            payload = SelfCaptureCreate(
                text="Was in an unplanned client call.",
                timestamp=timestamp,
                linked_gap_id=gap_event.id,
            )

            response = create_self_capture(payload, current_user=current_user, db=db)

            event_row = (
                db.query(Event)
                .filter(
                    Event.user_id == real_db_user,
                    Event.source == "self_capture",
                )
                .first()
            )
            assert event_row is not None
            assert event_row.event_metadata["self_capture_id"] == response.id
            assert event_row.event_metadata["linked_gap_id"] == gap_event.id
        finally:
            db.close()
