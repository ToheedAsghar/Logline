"""Plain, directly-callable function that reads events for a user/time range.

It is a standalone DB-read function that can be imported and called directly, e.g.
`get_existing_events(user_id=1, start_time=..., end_time=...)`.

Purpose: lets the agent check what's already been recorded for a user before
deciding what else to fetch, avoiding duplicate work across sessions.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.db.session import SessionLocal
from app.models.event import Event


class GetExistingEventsInput(BaseModel):
    """Strict input schema for `get_existing_events`. Extra/unrecognized fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    start_time: datetime
    end_time: datetime
    source: Optional[str] = None

    @model_validator(mode="after")
    def check_range(self) -> "GetExistingEventsInput":
        if self.start_time > self.end_time:
            raise ValueError("start_time must be before or equal to end_time")
        return self


class GetExistingEventsError(Exception):
    """Base error raised when existing events cannot be retrieved."""


class GetExistingEventsValidationError(GetExistingEventsError):
    """Raised when the input fails validation (missing fields, bad range, etc.)."""


def get_existing_events(**kwargs) -> list[dict]:
    """Validate `kwargs` and return events for `user_id` within `[start_time, end_time]`.

    Returns:
        A list of dicts, one per matching event, each with keys: id, source, type,
        timestamp, metadata, confidence. Ordered by timestamp ascending.

    Raises:
        GetExistingEventsValidationError: input is missing required fields, has the
            wrong type, or `start_time` is after `end_time`.
    """
    try:
        payload = GetExistingEventsInput(**kwargs)
    except ValidationError as exc:
        raise GetExistingEventsValidationError(str(exc)) from exc

    with SessionLocal() as db:
        query = db.query(Event).filter(
            Event.user_id == payload.user_id,
            Event.timestamp >= payload.start_time,
            Event.timestamp <= payload.end_time,
        )
        if payload.source is not None:
            query = query.filter(Event.source == payload.source)

        events = query.order_by(Event.timestamp.asc()).all()

    return [
        {
            "id": event.id,
            "source": event.source,
            "type": event.type,
            "timestamp": event.timestamp,
            "metadata": event.event_metadata,
            "confidence": event.confidence.value,
        }
        for event in events
    ]
