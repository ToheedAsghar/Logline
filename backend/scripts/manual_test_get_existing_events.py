"""Standalone script (not pytest) exercising app.agent.tools.get_existing_events against
a real Postgres database. Run from `backend/` with the venv active and Postgres up:

    python scripts/manual_test_get_existing_events.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.tools.get_existing_events import (
    GetExistingEventsValidationError,
    get_existing_events,
)
from app.agent.tools.write_event import write_event
from app.db.session import SessionLocal
from app.models.event import Event
from app.models.user import User

TEST_EMAIL = "get-existing-events-test@example.com"


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


def reset_events(user_id: int) -> None:
    """Delete any events left over from a previous run so seed counts stay exact."""
    db = SessionLocal()
    try:
        deleted = db.query(Event).filter(Event.user_id == user_id).delete()
        db.commit()
        if deleted:
            print(f"[setup] cleared {deleted} pre-existing event(s) for user_id={user_id}")
    finally:
        db.close()


def seed_events(user_id: int) -> None:
    print("\n--- Seeding sample events ---")
    seeds = [
        dict(
            user_id=user_id,
            source="calendar",
            type="meeting",
            timestamp="2026-07-04T09:00:00Z",
            metadata={"title": "Morning standup"},
            confidence="proven",
        ),
        dict(
            user_id=user_id,
            source="github",
            type="pull_request",
            timestamp="2026-07-04T11:00:00Z",
            metadata={"pr": 42},
            confidence="proven",
        ),
        dict(
            user_id=user_id,
            source="slack",
            type="message",
            timestamp="2026-07-04T20:00:00Z",
            metadata={"channel": "#eng"},
            confidence="estimated",
        ),
    ]
    for seed in seeds:
        result = write_event(**seed)
        print(f"[seed] wrote event_id={result['event_id']} source={seed['source']} timestamp={seed['timestamp']}")


def test_returns_events_within_range(user_id: int) -> None:
    print("\n--- Test 1: events within range are returned, events outside are excluded ---")
    results = get_existing_events(
        user_id=user_id,
        start_time="2026-07-04T08:00:00Z",
        end_time="2026-07-04T12:00:00Z",
    )
    print(f"get_existing_events returned {len(results)} event(s):")
    for row in results:
        print(f"  {row}")

    sources = {row["source"] for row in results}
    assert sources == {"calendar", "github"}, f"expected calendar+github only, got {sources}"
    for row in results:
        assert {"id", "source", "type", "timestamp", "metadata", "confidence"} == set(row.keys())
    print("[verified] range query included calendar+github events and excluded the later slack event")
    print("Test 1 PASSED")


def test_source_filter(user_id: int) -> None:
    print("\n--- Test 2: source filter narrows results ---")
    results = get_existing_events(
        user_id=user_id,
        start_time="2026-07-04T00:00:00Z",
        end_time="2026-07-04T23:59:59Z",
        source="slack",
    )
    print(f"get_existing_events(source='slack') returned {len(results)} event(s):")
    for row in results:
        print(f"  {row}")

    assert len(results) == 1
    assert results[0]["source"] == "slack"
    print("[verified] source filter returned only the slack event")
    print("Test 2 PASSED")


def test_invalid_range() -> None:
    print("\n--- Test 3: start_time after end_time is rejected ---")
    try:
        get_existing_events(
            user_id=1,
            start_time="2026-07-04T12:00:00Z",
            end_time="2026-07-04T08:00:00Z",
        )
    except GetExistingEventsValidationError as exc:
        print(f"[rejected as expected] GetExistingEventsValidationError: {exc}")
    else:
        raise AssertionError("expected GetExistingEventsValidationError, but call succeeded")
    print("Test 3 PASSED")


def main() -> None:
    user_id = get_or_create_test_user()
    reset_events(user_id)
    seed_events(user_id)
    test_returns_events_within_range(user_id)
    test_source_filter(user_id)
    test_invalid_range()
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
