from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.integrations.models import IntegrationSource, IntegrationStatus


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: IntegrationSource
    status: IntegrationStatus
    last_synced_at: datetime | None = None
    created_at: datetime
