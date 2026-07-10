from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.event import ConfidenceLevel


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    type: str
    timestamp: datetime
    event_metadata: dict | None = None
    confidence: ConfidenceLevel
    created_at: datetime


class EventUpdate(BaseModel):
    """Partial update for a single event, driven by the entry detail panel.

    `title`/`summary`/`end_timestamp` aren't real columns -- they live inside
    `event_metadata` (see backend CLAUDE.md's generic event shape), so the
    endpoint merges these into the existing dict rather than replacing it.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime | None = None
    end_timestamp: datetime | None = None
    title: str | None = None
    summary: str | None = None
    confidence: ConfidenceLevel | None = None
