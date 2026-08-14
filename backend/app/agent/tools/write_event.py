"""Plain, directly-callable function that writes a single row to the `events` table.

Used by `app/self_captures/routers.py` to record a self-capture as an Event. It is a standalone
DB-write function with no LLM/agent involvement, imported and called directly, e.g.
`write_event(user_id=1, source="calendar", ...)`.
"""

import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.timeline.models import ConfidenceLevel, Event


class WriteEventInput(BaseModel):
    """Strict input schema for `write_event`. Extra/unrecognized fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    source: str
    type: str
    timestamp: datetime
    metadata: Optional[dict] = None
    confidence: ConfidenceLevel
    external_id: Optional[str] = None


class WriteEventError(Exception):
    """Base error raised when an event cannot be written."""


class WriteEventValidationError(WriteEventError):
    """Raised when the input fails validation (missing fields, bad confidence, etc.)."""


class WriteEventDatabaseError(WriteEventError):
    """Raised when the database rejects the write (e.g. user_id doesn't exist)."""


# Slack's `ts` field (e.g. "1783404909.697459") is a raw Unix timestamp, not an
# ISO 8601 time-of-day. The model sometimes concatenates it onto today's date
# (e.g. "2026-07-07T1783404909.697459"), which Pydantic rejects outright. Both
# that concatenated form and a bare raw `ts` are detected and converted here
# rather than trusting the model to always format it correctly.
_CONCATENATED_DATE_AND_RAW_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T(\d{9,}(?:\.\d+)?)$")
_BARE_RAW_TS_RE = re.compile(r"^(\d{9,})(?:\.\d+)?$")


def _normalize_slack_timestamp(raw_timestamp: Any) -> Any:
    if not isinstance(raw_timestamp, str):
        return raw_timestamp

    concatenated_match = _CONCATENATED_DATE_AND_RAW_TS_RE.match(raw_timestamp)
    if concatenated_match:
        unix_ts = float(concatenated_match.group(1))
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()

    bare_match = _BARE_RAW_TS_RE.match(raw_timestamp)
    if bare_match:
        return datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc).isoformat()

    return raw_timestamp


def _find_existing_event(db, *, user_id: int, source: str, type: str, external_id: str) -> Optional[Event]:
    return (
        db.query(Event)
        .filter(
            Event.user_id == user_id,
            Event.source == source,
            Event.type == type,
            Event.external_id == external_id,
        )
        .first()
    )


def write_event(**kwargs) -> dict:
    """Validate `kwargs` and insert a new row into the `events` table.

    If `external_id` is provided and a row already exists for
    `(user_id, source, type, external_id)`, no new row is inserted -- the
    existing row's id is returned instead so the agent never has to treat a
    duplicate as an error.

    Returns:
        {"success": True, "status": "created", "event_id": <int>} on insert.
        {"success": True, "status": "already_exists", "event_id": <int>} if a
            row with the same (user_id, source, type, external_id) already exists.

    Raises:
        WriteEventValidationError: input is missing required fields, has the
            wrong type, or `confidence` is not one of "proven", "estimated", "gap".
        WriteEventDatabaseError: the insert fails at the database level, e.g. because
            `user_id` does not reference an existing user (foreign key violation).
    """
    if kwargs.get("source") == "slack" and "timestamp" in kwargs:
        kwargs["timestamp"] = _normalize_slack_timestamp(kwargs["timestamp"])

    try:
        payload = WriteEventInput(**kwargs)
    except ValidationError as exc:
        raise WriteEventValidationError(str(exc)) from exc

    with SessionLocal() as db:
        if payload.external_id is not None:
            existing = _find_existing_event(
                db,
                user_id=payload.user_id,
                source=payload.source,
                type=payload.type,
                external_id=payload.external_id,
            )
            if existing is not None:
                return {"success": True, "status": "already_exists", "event_id": existing.id}

        try:
            event = Event(
                user_id=payload.user_id,
                source=payload.source,
                type=payload.type,
                timestamp=payload.timestamp,
                event_metadata=payload.metadata,
                confidence=payload.confidence,
                external_id=payload.external_id,
            )
            db.add(event)
            db.commit()
            db.refresh(event)
        except IntegrityError as exc:
            db.rollback()
            # If this raced against another insert of the same identity key, the
            # DB-level unique constraint (the real backstop -- see
            # uq_events_user_source_type_external_id) rejected it after our
            # pre-check above missed it. Treat that the same as a normal
            # duplicate rather than surfacing a generic DB error.
            if payload.external_id is not None:
                existing = _find_existing_event(
                    db,
                    user_id=payload.user_id,
                    source=payload.source,
                    type=payload.type,
                    external_id=payload.external_id,
                )
                if existing is not None:
                    return {"success": True, "status": "already_exists", "event_id": existing.id}
            raise WriteEventDatabaseError(
                f"Could not write event, likely an invalid user_id: {exc}"
            ) from exc

    return {"success": True, "status": "created", "event_id": event.id}
