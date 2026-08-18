from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.tracker_sync.constants import DEVICE_NAME_MAX_LENGTH


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


class DeviceEnrollIn(BaseModel):
    """Enrollment request. `name` is supplied by the client (typically the machine's hostname) because the server
    cannot know it; a blank or omitted name falls back to a generic default rather than being rejected."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=DEVICE_NAME_MAX_LENGTH)


class DeviceEnrollOut(BaseModel):
    """Enrollment response. `token` appears here and nowhere else, ever -- only its hash is persisted, so this
    response is the single opportunity to capture it."""

    device_id: UUID
    name: str
    token: str
    created_at: datetime


class DeviceOut(BaseModel):
    """A device without its secret, for the revoke response."""

    model_config = ConfigDict(from_attributes=True)

    device_id: UUID
    name: str
    created_at: datetime
    revoked_at: datetime | None


class SyncStatusOut(BaseModel):
    """User-facing sync health, for surfacing staleness in the frontend.

    `last_synced_at` is the newest checkpoint across all of the user's active devices, so a second machine that
    synced more recently does not make the account look stale. It is None when nothing has ever synced.
    """

    last_synced_at: datetime | None
    device_count: int
