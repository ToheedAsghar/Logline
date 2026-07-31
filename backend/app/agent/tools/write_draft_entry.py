"""Plain, directly-callable function that writes a single row to the `entries` table
with status="draft".

This is a *tool* the agent will eventually be able to invoke, but this module makes
no assumption about which LLM API (Anthropic, OpenAI, or otherwise) drives that agent,
and does not call any LLM. It is a standalone DB-write function that can be imported
and called directly, e.g. `write_draft_entry(user_id=1, format="standup", content={...})`.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.entries.models import Entry, EntryFormat, EntryStatus
from app.entries.schemas import parse_entry_content


class DraftEntryInput(BaseModel):
    """Strict input schema for `write_draft_entry`. Extra/unrecognized fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    format: EntryFormat
    content: dict
    work_date: date


class WriteDraftEntryError(Exception):
    """Base error raised when a draft entry cannot be written."""


class WriteDraftEntryValidationError(WriteDraftEntryError):
    """Raised when input fails validation, or `content` doesn't match `format`'s
    required shape ({yesterday, today, blockers} for standup; {text} for project_log)."""


class WriteDraftEntryDatabaseError(WriteDraftEntryError):
    """Raised when the database rejects the write (e.g. user_id doesn't exist)."""


def write_draft_entry(**kwargs) -> dict:
    """Validate `kwargs` and insert a new draft row into the `entries` table.

    `content` is validated against `format`'s required shape using the same
    `parse_entry_content` validator the REST API uses (app/entries/schemas.py),
    so the agent and the API can never disagree on what counts as valid content.

    `work_date` is the actual calendar day this entry's content is about (not
    today's date, unless the entry happens to be about today) -- it drives
    retention decisions later (app/tracker_sync), so it must reflect the real
    day being reported on, not the day the draft happens to be written.

    Returns:
        {"success": True, "status": "created", "entry_id": <int>} on insert.

    Raises:
        WriteDraftEntryValidationError: input is missing required fields, has the
            wrong type, `format` is not "standup"/"project_log", or `content` doesn't
            match the required shape for `format`.
        WriteDraftEntryDatabaseError: the insert fails at the database level, e.g.
            because `user_id` does not reference an existing user (foreign key
            violation).
    """
    try:
        payload = DraftEntryInput(**kwargs)
    except ValidationError as exc:
        raise WriteDraftEntryValidationError(str(exc)) from exc

    try:
        validated_content = parse_entry_content(payload.format, payload.content)
    except ValidationError as exc:
        raise WriteDraftEntryValidationError(str(exc)) from exc

    with SessionLocal() as db:
        try:
            entry = Entry(
                user_id=payload.user_id,
                format=payload.format,
                content=validated_content.model_dump(),
                work_date=payload.work_date,
                status=EntryStatus.draft,
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
        except IntegrityError as exc:
            db.rollback()
            raise WriteDraftEntryDatabaseError(
                f"Could not write draft entry, likely an invalid user_id: {exc}"
            ) from exc

    return {"success": True, "status": "created", "entry_id": entry.id}
