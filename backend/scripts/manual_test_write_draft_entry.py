"""Standalone script (not pytest) exercising app.agent.tools.write_draft_entry against
a real Postgres database. Run from `backend/` with the venv active and Postgres up:

    python scripts/manual_test_write_draft_entry.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.tools.write_draft_entry import WriteDraftEntryValidationError, write_draft_entry
from app.agent.tools.write_event import write_event
from app.auth.models import User
from app.db import base  # noqa: F401 -- registers every domain's models before any User query
from app.db.session import SessionLocal
from app.entries.models import Entry, EntryStatus
from app.timeline.models import Event

TEST_EMAIL = "write-draft-entry-test@example.com"


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


def reset_events_and_entries(user_id: int) -> None:
    """Delete any events/entries left over from a previous run so counts stay exact."""
    db = SessionLocal()
    try:
        deleted_events = db.query(Event).filter(Event.user_id == user_id).delete()
        deleted_entries = db.query(Entry).filter(Entry.user_id == user_id).delete()
        db.commit()
        if deleted_events or deleted_entries:
            print(
                f"[setup] cleared {deleted_events} event(s) and {deleted_entries} "
                f"entry(ies) left over from a previous run for user_id={user_id}"
            )
    finally:
        db.close()


def seed_events(user_id: int) -> None:
    print("\n--- Seeding sample events ---")
    seeds = [
        dict(
            user_id=user_id,
            source="calendar",
            type="meeting",
            timestamp="2026-07-07T09:00:00Z",
            metadata={"title": "Morning standup"},
            confidence="proven",
        ),
        dict(
            user_id=user_id,
            source="github",
            type="pull_request",
            timestamp="2026-07-07T14:00:00Z",
            metadata={"pr": 51, "title": "Add write_draft_entry tool"},
            confidence="proven",
        ),
    ]
    for seed in seeds:
        result = write_event(**seed)
        print(f"[seed] wrote event_id={result['event_id']} source={seed['source']} timestamp={seed['timestamp']}")


def count_entries() -> int:
    db = SessionLocal()
    try:
        return db.query(Entry).count()
    finally:
        db.close()


def test_valid_standup(user_id: int) -> None:
    print("\n--- Test 1: valid standup content ---")
    result = write_draft_entry(
        user_id=user_id,
        format="standup",
        content={
            "yesterday": "Attended morning standup; no other recorded activity.",
            "today": "Opened PR #51 adding the write_draft_entry tool.",
            "blockers": "No blockers.",
        },
    )
    print(f"write_draft_entry returned: {result}")
    assert result["success"] is True
    entry_id = result["entry_id"]

    db = SessionLocal()
    try:
        row = db.query(Entry).filter(Entry.id == entry_id).first()
        assert row is not None, "entry row was not found in Postgres"
        assert row.user_id == user_id
        assert row.format.value == "standup"
        assert row.status == EntryStatus.draft
        assert set(row.content.keys()) == {"yesterday", "today", "blockers"}
        print(f"[verified] entry id={row.id} present in Postgres with expected fields")
    finally:
        db.close()

    print("Test 1 PASSED")


def test_valid_project_log(user_id: int) -> None:
    print("\n--- Test 2: valid project_log content ---")
    result = write_draft_entry(
        user_id=user_id,
        format="project_log",
        content={
            "text": (
                "Attended the morning standup and opened PR #51 adding the "
                "write_draft_entry tool."
            )
        },
    )
    print(f"write_draft_entry returned: {result}")
    assert result["success"] is True
    entry_id = result["entry_id"]

    db = SessionLocal()
    try:
        row = db.query(Entry).filter(Entry.id == entry_id).first()
        assert row is not None, "entry row was not found in Postgres"
        assert row.user_id == user_id
        assert row.format.value == "project_log"
        assert row.status == EntryStatus.draft
        assert set(row.content.keys()) == {"text"}
        print(f"[verified] entry id={row.id} present in Postgres with expected fields")
    finally:
        db.close()

    print("Test 2 PASSED")


def test_malformed_standup_content(user_id: int) -> None:
    print("\n--- Test 3: malformed standup content (missing 'blockers') is rejected ---")
    before = count_entries()
    try:
        write_draft_entry(
            user_id=user_id,
            format="standup",
            content={
                "yesterday": "Attended morning standup.",
                "today": "Opened PR #51.",
                # "blockers" intentionally omitted
            },
        )
    except WriteDraftEntryValidationError as exc:
        print(f"[rejected as expected] WriteDraftEntryValidationError: {exc}")
    else:
        raise AssertionError("expected WriteDraftEntryValidationError, but write_draft_entry succeeded")

    after = count_entries()
    assert before == after, f"row count changed ({before} -> {after}); DB was touched despite invalid input"
    print(f"[verified] entries row count unchanged ({before} -> {after})")
    print("Test 3 PASSED")


def test_malformed_project_log_content(user_id: int) -> None:
    print("\n--- Test 4: malformed project_log content (wrong key 'notes') is rejected ---")
    before = count_entries()
    try:
        write_draft_entry(
            user_id=user_id,
            format="project_log",
            content={"notes": "Wrong key name instead of 'text'."},
        )
    except WriteDraftEntryValidationError as exc:
        print(f"[rejected as expected] WriteDraftEntryValidationError: {exc}")
    else:
        raise AssertionError("expected WriteDraftEntryValidationError, but write_draft_entry succeeded")

    after = count_entries()
    assert before == after, f"row count changed ({before} -> {after}); DB was touched despite invalid input"
    print(f"[verified] entries row count unchanged ({before} -> {after})")
    print("Test 4 PASSED")


def main() -> None:
    user_id = get_or_create_test_user()
    reset_events_and_entries(user_id)
    seed_events(user_id)
    test_valid_standup(user_id)
    test_valid_project_log(user_id)
    test_malformed_standup_content(user_id)
    test_malformed_project_log_content(user_id)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
