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
