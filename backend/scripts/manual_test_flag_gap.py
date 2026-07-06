"""Standalone script (not pytest) exercising app.agent.tools.flag_gap against a
real Postgres database. Run from `backend/` with the venv active and Postgres up:

    python scripts/manual_test_flag_gap.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.tools.flag_gap import FlagGapValidationError, flag_gap
from app.agent.tools.write_event import write_event
from app.db.session import SessionLocal
from app.models.event import Event
from app.models.user import User

TEST_EMAIL = "flag-gap-test@example.com"


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
            timestamp="2026-07-05T09:00:00Z",
            metadata={"title": "Morning standup"},
            confidence="proven",
        ),
        dict(
            user_id=user_id,
            source="github",
            type="pull_request",
            timestamp="2026-07-05T10:00:00Z",
            metadata={"pr": 43},
            confidence="proven",
        ),
    ]
    for seed in seeds:
        result = write_event(**seed)
        print(f"[seed] wrote event_id={result['event_id']} source={seed['source']} timestamp={seed['timestamp']}")


def test_uncovered_range_is_gap(user_id: int) -> None:
    print("\n--- Test 1: uncovered range is flagged as a gap ---")
    result = flag_gap(
        user_id=user_id,
        start_time="2026-07-05T14:00:00Z",
        end_time="2026-07-05T16:00:00Z",
    )
    print(f"flag_gap returned: {result}")
    assert result["is_gap"] is True
    assert result["context"] == "no recorded activity"
    assert result["duration_minutes"] == 120
    print("[verified] range with no events was correctly identified as a gap")
    print("Test 1 PASSED")


def test_covered_range_is_not_gap(user_id: int) -> None:
    print("\n--- Test 2: covered range is NOT flagged as a gap ---")
    result = flag_gap(
        user_id=user_id,
        start_time="2026-07-05T08:30:00Z",
        end_time="2026-07-05T10:30:00Z",
    )
    print(f"flag_gap returned: {result}")
    assert result["is_gap"] is False
    assert result["event_count"] == 2
    assert result["context"] == "existing events cover this range"
    print("[verified] range with existing events was correctly identified as NOT a gap")
    print("Test 2 PASSED")


def test_invalid_range() -> None:
    print("\n--- Test 3: start_time after end_time is rejected ---")
    try:
        flag_gap(
            user_id=1,
            start_time="2026-07-05T12:00:00Z",
            end_time="2026-07-05T08:00:00Z",
        )
    except FlagGapValidationError as exc:
        print(f"[rejected as expected] FlagGapValidationError: {exc}")
    else:
        raise AssertionError("expected FlagGapValidationError, but call succeeded")
    print("Test 3 PASSED")


def main() -> None:
    user_id = get_or_create_test_user()
    reset_events(user_id)
    seed_events(user_id)
    test_uncovered_range_is_gap(user_id)
    test_covered_range_is_not_gap(user_id)
    test_invalid_range()
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
