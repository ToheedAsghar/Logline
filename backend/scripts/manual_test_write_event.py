"""Standalone script (not pytest) exercising app.agent.tools.write_event against a
real Postgres database. Run from `backend/` with the venv active and Postgres up:

    python scripts/manual_test_write_event.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.tools.write_event import WriteEventValidationError, write_event
from app.auth.models import User
from app.db import base  # noqa: F401 -- registers every domain's models before any User query
from app.db.session import SessionLocal
from app.timeline.models import Event

TEST_EMAIL = "write-event-test@example.com"


def get_or_create_test_user() -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if user is None:
            user = User(email=TEST_EMAIL, hashed_password="not-a-real-hash")
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"[setup] created test user id={user.id}")
        else:
            print(f"[setup] reusing existing test user id={user.id}")
        return user.id
    finally:
        db.close()


def count_events() -> int:
    db = SessionLocal()
    try:
        return db.query(Event).count()
    finally:
        db.close()


def test_valid_input(user_id: int) -> None:
    print("\n--- Test 1: valid input ---")
    result = write_event(
        user_id=user_id,
        source="calendar",
        type="meeting",
        timestamp="2026-07-04T10:00:00Z",
        metadata={"title": "Standup"},
        confidence="proven",
    )
    print(f"write_event returned: {result}")
    assert result["success"] is True
    event_id = result["event_id"]

    db = SessionLocal()
    try:
        row = db.query(Event).filter(Event.id == event_id).first()
        assert row is not None, "event row was not found in Postgres"
        assert row.user_id == user_id
        assert row.source == "calendar"
        assert row.confidence.value == "proven"
        assert row.event_metadata == {"title": "Standup"}
        print(f"[verified] event id={row.id} present in Postgres with expected fields")
    finally:
        db.close()

    print("Test 1 PASSED")


def test_invalid_confidence(user_id: int) -> None:
    print("\n--- Test 2: invalid confidence value ---")
    before = count_events()
    try:
        write_event(
            user_id=user_id,
            source="calendar",
            type="meeting",
            timestamp="2026-07-04T10:00:00Z",
            confidence="definitely-not-a-real-level",
        )
    except WriteEventValidationError as exc:
        print(f"[rejected as expected] WriteEventValidationError: {exc}")
    else:
        raise AssertionError("expected WriteEventValidationError, but write_event succeeded")

    after = count_events()
    assert before == after, f"row count changed ({before} -> {after}); DB was touched despite invalid input"
    print(f"[verified] events row count unchanged ({before} -> {after})")
    print("Test 2 PASSED")


def main() -> None:
    user_id = get_or_create_test_user()
    test_valid_input(user_id)
    test_invalid_confidence(user_id)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
