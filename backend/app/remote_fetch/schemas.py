"""Response shapes and cursor encoding for `GET /remote-events`.

The fetch-side types (FetchedEvent, SourceFetcher etc.) live in `base.py`. These schemas serve the
read API surface and live in their own file so the write-shape types and read-shape types don't
share a namespace within the same module.
"""

import base64
import binascii
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.integrations.models import IntegrationSource


class RemoteEventResponse(BaseModel):
    """One fetched remote event, deliberately without `raw_data`.

    The raw provider payload stays server-side: the log views show summary and description only, per the
    remote-logs page sign-off, so a raw event never leaks through the list API by default.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: IntegrationSource
    event_type: str
    occurred_at: datetime
    summary: str | None
    description: str | None
    remote_project_id: str | None
    match_keys: dict | None = None


class RemoteEventListResponse(BaseModel):
    """One page of remote events plus the opaque keyset cursor to the next.

    `next_cursor` is present exactly when `has_more` is true.
    """

    events: list[RemoteEventResponse]
    next_cursor: str | None
    has_more: bool


def encode_cursor(occurred_at: datetime, row_id: int) -> str:
    """Encode the last seen row's (occurred_at, id) as an opaque, URL-safe page cursor."""
    payload = json.dumps({"occurred_at": occurred_at.isoformat(), "id": row_id})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode an `encode_cursor` value back into its (occurred_at, id) key pair.

    Raises ValueError on any malformed or timezone-naive input so the caller can answer 422 without leaking
    the cursor's internal format.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        occurred_at = datetime.fromisoformat(payload["occurred_at"])
        row_id = int(payload["id"])
    except (binascii.Error, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
    if occurred_at.tzinfo is None:
        raise ValueError("Invalid pagination cursor")
    return occurred_at, row_id
