from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LocalSessionIn(BaseModel):
    """Data structure representing one incoming session from the tracker.

    This represents the raw session object received from the user's tracker.
    Note that `user_id` is omitted here because it is provided separately by the backend API context.

    `ended_at` and `end_reason` are optional on incoming records because the tracker may send
    sessions that are still open or not yet finalized. Only sessions with both fields filled in
    are considered finished and ready to be stored in the database.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    bundle_id: str
    app_name: str
    window_title: str | None = None
    project_path: str | None = None
    context_detail: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    is_idle: bool


class SyncPayload(BaseModel):
    """Payload for the tracker sync endpoint."""
    device_id: UUID
    sessions: list[LocalSessionIn]
