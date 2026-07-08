from datetime import datetime

from pydantic import BaseModel

from app.schemas.event import EventResponse


class AgentRunDateRange(BaseModel):
    start: datetime
    end: datetime


class AgentRunRequest(BaseModel):
    task: str
    date_range: AgentRunDateRange | None = None


class AgentRunResponse(BaseModel):
    response: str
    events: list[EventResponse]
