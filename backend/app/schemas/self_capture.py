from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SelfCaptureCreate(BaseModel):
    text: str
    timestamp: datetime
    linked_gap_id: int | None = None


class SelfCaptureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    text: str
    timestamp: datetime
    linked_gap_id: int | None = None
    created_at: datetime
