"""Plain, directly-callable function that computes whether a time range is a gap.

Gaps are computed dynamically, not stored: this function does NOT write a row to
any table. It reads the `events` table for the given user/range and reports
whether that range is covered by existing events or not.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.db.session import SessionLocal
from app.models.event import Event


class FlagGapInput(BaseModel):
    """Strict input schema for `flag_gap`. Extra/unrecognized fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def check_range(self) -> "FlagGapInput":
        if self.start_time > self.end_time:
            raise ValueError("start_time must be before or equal to end_time")
        return self


class FlagGapError(Exception):
    """Base error raised when a gap cannot be computed."""


class FlagGapValidationError(FlagGapError):
    """Raised when the input fails validation (missing fields, bad range, etc.)."""


def flag_gap(**kwargs) -> dict:
    """Validate `kwargs` and determine whether `[start_time, end_time]` is a gap.

    This is a read/compute function only — it never writes to the `events` table.

    Returns:
        If no events exist covering the range:
            {"is_gap": True, "start_time": ..., "end_time": ..., "duration_minutes": ...,
             "context": "no recorded activity"}
        If events exist covering the range:
            {"is_gap": False, "start_time": ..., "end_time": ..., "event_count": ...,
             "context": "existing events cover this range"}

    Raises:
        FlagGapValidationError: input is missing required fields, has the wrong
            type, or `start_time` is after `end_time`.
    """
    try:
        payload = FlagGapInput(**kwargs)
    except ValidationError as exc:
        raise FlagGapValidationError(str(exc)) from exc

    with SessionLocal() as db:
        event_count = (
            db.query(Event)
            .filter(
                Event.user_id == payload.user_id,
                Event.timestamp >= payload.start_time,
                Event.timestamp <= payload.end_time,
            )
            .count()
        )

    duration_minutes = (payload.end_time - payload.start_time).total_seconds() / 60

    if event_count == 0:
        return {
            "is_gap": True,
            "start_time": payload.start_time,
            "end_time": payload.end_time,
            "duration_minutes": duration_minutes,
            "context": "no recorded activity",
        }

    return {
        "is_gap": False,
        "start_time": payload.start_time,
        "end_time": payload.end_time,
        "event_count": event_count,
        "context": "existing events cover this range",
    }
