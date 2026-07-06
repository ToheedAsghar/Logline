"""Plain, directly-callable function that writes a single row to the `events` table.

This is a *tool* the agent will eventually be able to invoke, but this module makes
no assumption about which LLM API (Anthropic, OpenAI, or otherwise) drives that agent,
and does not call any LLM. It is a standalone DB-write function that can be imported
and called directly, e.g. `write_event(user_id=1, source="calendar", ...)`.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.event import ConfidenceLevel, Event


class WriteEventInput(BaseModel):
    """Strict input schema for `write_event`. Extra/unrecognized fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    source: str
    type: str
    timestamp: datetime
    metadata: Optional[dict] = None
    confidence: ConfidenceLevel


class WriteEventError(Exception):
    """Base error raised when an event cannot be written."""


class WriteEventValidationError(WriteEventError):
    """Raised when the input fails validation (missing fields, bad confidence, etc.)."""


class WriteEventDatabaseError(WriteEventError):
    """Raised when the database rejects the write (e.g. user_id doesn't exist)."""


def write_event(**kwargs) -> dict:
    """Validate `kwargs` and insert a new row into the `events` table.

    Returns:
        {"success": True, "event_id": <int>} on success.

    Raises:
        WriteEventValidationError: input is missing required fields, has the wrong
            type, or `confidence` is not one of "proven", "estimated", "gap".
        WriteEventDatabaseError: the insert fails at the database level, e.g. because
            `user_id` does not reference an existing user (foreign key violation).
    """
    try:
        payload = WriteEventInput(**kwargs)
    except ValidationError as exc:
        raise WriteEventValidationError(str(exc)) from exc

    with SessionLocal() as db:
        try:
            event = Event(
                user_id=payload.user_id,
                source=payload.source,
                type=payload.type,
                timestamp=payload.timestamp,
                event_metadata=payload.metadata,
                confidence=payload.confidence,
            )
            db.add(event)
            db.commit()
            db.refresh(event)
        except IntegrityError as exc:
            db.rollback()
            raise WriteEventDatabaseError(
                f"Could not write event, likely an invalid user_id: {exc}"
            ) from exc

    return {"success": True, "event_id": event.id}
