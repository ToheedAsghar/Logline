"""
Regression tests for the three-layer duplicate-prevention fix in write_event
(app/agent/tools/write_event.py) and the Slack raw-timestamp conversion that
lives alongside it.

Layer 1 (the real guarantee, Python-level) and Layer 2 (DB-level backstop)
are both covered here:

- TestWriteEventSkipsExactDuplicate / TestWriteEventInsertsGenuinelyNewEvent
  mock SessionLocal (same pattern as test_calendar_location_exclusion.py) to
  pin write_event's pre-insert dedup check: same
  (user_id, source, type, external_id) -> skip and return "already_exists"
  without ever calling db.add(); a new external_id -> insert normally.
- TestDatabaseConstraintRejectsBypassedDuplicate hits the real test Postgres
  database (docker-compose, same as scripts/manual_test_write_event.py) to
  prove the actual uq_events_user_source_type_external_id constraint -- not
  just the Python check -- rejects a duplicate insert, e.g. if the Python
  check were ever bypassed or two writers race.
- TestSlackTimestampConversion pins the raw-Unix-ts -> ISO 8601 conversion
  that makes Slack writes succeed at all.

No real LLM/MCP calls are made anywhere in this file.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

import app.agent.tools.write_event as write_event_module
from app.agent.tools.write_event import (
    WriteEventDatabaseError,
    WriteEventValidationError,
    _normalize_slack_timestamp,
    write_event,
)
from app.db.session import SessionLocal
from app.models.event import ConfidenceLevel, Event
from app.models.user import User


def _fake_session_cm(fake_db: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value = fake_db
    cm.__exit__.return_value = False
    return cm


class TestWriteEventSkipsExactDuplicate:
    def test_matching_identity_key_skips_insert_and_returns_existing_id(self, monkeypatch):
        existing_row = MagicMock(id=101)
        fake_query = MagicMock()
        fake_query.filter.return_value.first.return_value = existing_row
        fake_db = MagicMock()
        fake_db.query.return_value = fake_query
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: _fake_session_cm(fake_db))

        result = write_event(
            user_id=9,
            source="github",
            type="commit",
            timestamp="2026-07-07T05:23:04Z",
            metadata={"sha": "abc123"},
            confidence=ConfidenceLevel.proven,
            external_id="abc123",
        )

        assert result == {"success": True, "status": "already_exists", "event_id": 101}
        fake_db.add.assert_not_called()
        fake_db.commit.assert_not_called()

    def test_no_external_id_never_dedup_checks_and_always_inserts(self, monkeypatch):
        fake_db = MagicMock()
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: _fake_session_cm(fake_db))

        write_event(
            user_id=9,
            source="calendar",
            type="meeting",
            timestamp="2026-07-07T06:00:00Z",
            confidence=ConfidenceLevel.gap,
        )

        fake_db.query.assert_not_called()
        fake_db.add.assert_called_once()


class TestWriteEventInsertsGenuinelyNewEvent:
    def test_new_identity_key_inserts_and_reports_created(self, monkeypatch):
        fake_query = MagicMock()
        fake_query.filter.return_value.first.return_value = None
        fake_db = MagicMock()
        fake_db.query.return_value = fake_query

        def fake_refresh(event):
            event.id = 202

        fake_db.refresh.side_effect = fake_refresh
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: _fake_session_cm(fake_db))

        result = write_event(
            user_id=9,
            source="github",
            type="commit",
            timestamp="2026-07-07T05:23:04Z",
            metadata={"sha": "def456"},
            confidence=ConfidenceLevel.proven,
            external_id="def456",
        )

        assert result == {"success": True, "status": "created", "event_id": 202}
        fake_db.add.assert_called_once()
        written_event = fake_db.add.call_args.args[0]
        assert written_event.external_id == "def456"


class TestWriteEventRaceBackstop:
    def test_integrity_error_on_insert_resolves_to_already_exists_if_row_now_present(self, monkeypatch):
        """Simulates two racing writers: the pre-insert check (first .first())
        sees nothing, the insert then hits the real unique constraint
        (IntegrityError) because the other writer beat it to the commit, and
        the post-error re-check (second .first()) now finds that row."""
        winner_row = MagicMock(id=303)
        fake_query = MagicMock()
        fake_query.filter.return_value.first.side_effect = [None, winner_row]
        fake_db = MagicMock()
        fake_db.query.return_value = fake_query
        fake_db.commit.side_effect = IntegrityError("stmt", "params", Exception("unique violation"))
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: _fake_session_cm(fake_db))

        result = write_event(
            user_id=9,
            source="slack",
            type="message",
            timestamp="2026-07-07T05:15:09.697459+00:00",
            confidence=ConfidenceLevel.proven,
            external_id="C123:1783404909.697459",
        )

        assert result == {"success": True, "status": "already_exists", "event_id": 303}
        fake_db.rollback.assert_called_once()

    def test_integrity_error_without_matching_row_still_raises(self, monkeypatch):
        """A non-duplicate IntegrityError (e.g. bad user_id) must still surface
        as an error rather than being silently swallowed as a duplicate."""
        fake_query = MagicMock()
        fake_query.filter.return_value.first.return_value = None
        fake_db = MagicMock()
        fake_db.query.return_value = fake_query
        fake_db.commit.side_effect = IntegrityError("stmt", "params", Exception("fk violation"))
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: _fake_session_cm(fake_db))

        with pytest.raises(WriteEventDatabaseError):
            write_event(
                user_id=999999,
                source="github",
                type="commit",
                timestamp="2026-07-07T05:23:04Z",
                confidence=ConfidenceLevel.proven,
                external_id="xyz",
            )


TEST_EMAIL = "write-event-dedup-constraint-test@example.com"


@pytest.fixture
def real_db_user():
    """Real Postgres row (same DB the app/agent runs against, see
    backend/CLAUDE.md's docker-compose Postgres) -- needed here because a
    mocked session can't prove the actual DB constraint fires."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
        db.query(Event).filter(Event.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()

    yield user_id

    db = SessionLocal()
    try:
        db.query(Event).filter(Event.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


class TestDatabaseConstraintRejectsBypassedDuplicate:
    """Layer 2: even if the Python pre-check in write_event were skipped
    entirely, the DB itself must refuse a second identical
    (user_id, source, type, external_id) row."""

    def test_unique_constraint_rejects_duplicate_insert_bypassing_python_check(self, real_db_user):
        db = SessionLocal()
        try:
            db.add(
                Event(
                    user_id=real_db_user,
                    source="github",
                    type="commit",
                    timestamp=datetime(2026, 7, 7, tzinfo=timezone.utc),
                    confidence=ConfidenceLevel.proven,
                    external_id="constraint-test-sha",
                )
            )
            db.commit()

            db.add(
                Event(
                    user_id=real_db_user,
                    source="github",
                    type="commit",
                    timestamp=datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
                    confidence=ConfidenceLevel.proven,
                    external_id="constraint-test-sha",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.rollback()
            db.close()

    def test_unique_constraint_allows_multiple_null_external_ids(self, real_db_user):
        """NULLs are distinct in Postgres unique constraints -- two events
        genuinely lacking any identity key must not be forced-unique."""
        db = SessionLocal()
        try:
            db.add(
                Event(
                    user_id=real_db_user,
                    source="calendar",
                    type="meeting",
                    timestamp=datetime(2026, 7, 7, tzinfo=timezone.utc),
                    confidence=ConfidenceLevel.gap,
                    external_id=None,
                )
            )
            db.add(
                Event(
                    user_id=real_db_user,
                    source="calendar",
                    type="meeting",
                    timestamp=datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
                    confidence=ConfidenceLevel.gap,
                    external_id=None,
                )
            )
            db.commit()
        finally:
            db.close()


class TestSlackTimestampConversion:
    def test_concatenated_date_and_raw_ts_converts_to_iso8601(self):
        result = _normalize_slack_timestamp("2026-07-07T1783404909.697459")
        assert result == datetime.fromtimestamp(1783404909.697459, tz=timezone.utc).isoformat()

    def test_bare_raw_ts_converts_to_iso8601(self):
        result = _normalize_slack_timestamp("1783404909.697459")
        assert result == datetime.fromtimestamp(1783404909.697459, tz=timezone.utc).isoformat()

    def test_already_valid_iso8601_is_left_untouched(self):
        result = _normalize_slack_timestamp("2026-07-07T05:15:09.697459+00:00")
        assert result == "2026-07-07T05:15:09.697459+00:00"

    def test_write_event_auto_corrects_slack_timestamp_before_validation(self, monkeypatch):
        fake_query = MagicMock()
        fake_query.filter.return_value.first.return_value = None
        fake_db = MagicMock()
        fake_db.query.return_value = fake_query

        def fake_refresh(event):
            event.id = 404

        fake_db.refresh.side_effect = fake_refresh
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: _fake_session_cm(fake_db))

        result = write_event(
            user_id=9,
            source="slack",
            type="message",
            timestamp="2026-07-07T1783404909.697459",
            metadata={"channel_id": "C123", "ts": "1783404909.697459"},
            confidence=ConfidenceLevel.proven,
            external_id="C123:1783404909.697459",
        )

        assert result["success"] is True
        written_event = fake_db.add.call_args.args[0]
        assert written_event.timestamp == datetime.fromtimestamp(1783404909.697459, tz=timezone.utc)

    def test_non_slack_source_timestamp_is_never_touched(self, monkeypatch):
        """The Slack-specific conversion must not fire for other sources --
        a numeric-looking value from another source should fail validation
        normally rather than being silently reinterpreted."""
        fake_db = MagicMock()
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: _fake_session_cm(fake_db))

        with pytest.raises(WriteEventValidationError):
            write_event(
                user_id=9,
                source="github",
                type="commit",
                timestamp="2026-07-07T1783404909.697459",
                confidence=ConfidenceLevel.proven,
            )
