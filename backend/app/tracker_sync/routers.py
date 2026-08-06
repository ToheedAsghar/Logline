from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_tracker_device
from app.auth.models import User
from app.db.session import get_db
from app.tracker_sync import crud, service
from app.tracker_sync.constants import DEFAULT_DEVICE_NAME, DEVICE_MISMATCH_ERROR_MSG, DEVICE_NOT_FOUND_ERROR_MSG
from app.tracker_sync.models import TrackerDevice, TrackerSyncState
from app.tracker_sync.schemas import DeviceEnrollIn, DeviceEnrollOut, DeviceOut, SyncPayload, SyncStatusOut

router = APIRouter(prefix="/tracker", tags=["tracker"])


class CheckpointResponse(BaseModel):
    """`device_id` is echoed back so the sync agent can learn its own identity from its token alone, and needs no
    local state beyond the token file."""

    device_id: UUID
    last_synced_at: datetime | None


@router.post("/devices", response_model=DeviceEnrollOut, status_code=status.HTTP_201_CREATED)
def enroll_device(
    payload: DeviceEnrollIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enroll a tracker device for the logged-in user and issue its sync token.

    The token in this response is the only copy that will ever exist: the database holds only a hash, and there is
    no recovery endpoint by design. A client that loses it must enroll again.
    """
    name = (payload.name or "").strip() or DEFAULT_DEVICE_NAME
    device, token = crud.create_device(db, user_id=user.id, name=name)
    return DeviceEnrollOut(
        device_id=device.device_id,
        name=device.name,
        token=token,
        created_at=device.created_at,
    )


@router.delete("/devices/{device_id}", response_model=DeviceOut)
def revoke_device(
    device_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke a device's token, immediately ending its ability to sync. Idempotent.

    The device row and its sync checkpoint survive revocation, so re-enrolling the same machine resumes from where
    it left off rather than replaying its entire local history.
    """
    device = crud.revoke_device(db, user_id=user.id, device_id=device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=DEVICE_NOT_FOUND_ERROR_MSG)
    return DeviceOut.model_validate(device)


@router.get("/sync/status", response_model=SyncStatusOut)
def get_sync_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync freshness for the logged-in user, for surfacing staleness in the UI.

    Separate from `/tracker/sync/checkpoint`, which authenticates a device token a browser session does not have.
    """
    last_synced_at, device_count = crud.get_sync_status(db, user_id=user.id)
    return SyncStatusOut(last_synced_at=last_synced_at, device_count=device_count)


@router.get("/sync/checkpoint", response_model=CheckpointResponse)
def get_sync_checkpoint(
    device: TrackerDevice = Depends(get_tracker_device),
    db: Session = Depends(get_db),
):
    """Get the high-water mark for the authenticated tracker device to avoid re-syncing old data."""
    state = (
        db.query(TrackerSyncState)
        .filter(
            TrackerSyncState.user_id == device.user_id,
            TrackerSyncState.device_id == device.device_id,
        )
        .first()
    )
    return CheckpointResponse(
        device_id=device.device_id,
        last_synced_at=state.last_synced_at if state else None,
    )


@router.post("/sync")
def sync_sessions(
    payload: SyncPayload,
    device: TrackerDevice = Depends(get_tracker_device),
    db: Session = Depends(get_db),
):
    """Sync a batch of local tracker sessions to the backend database.

    This performs an idempotent upsert, so retrying the same batch is safe. Updates the sync checkpoint automatically
    based on the latest ended_at timestamp among accepted and duplicate sessions in the processed batch.
    """
    if payload.device_id is not None and payload.device_id != device.device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DEVICE_MISMATCH_ERROR_MSG,
        )

    result = service.ingest_sessions(db, user_id=device.user_id, sessions=payload.sessions)

    kept_ids = {
        r.id
        for r in result.results
        if r.status in (service.IngestStatus.accepted, service.IngestStatus.duplicate)
    }
    kept_sessions = [s for s in payload.sessions if s.id in kept_ids and s.ended_at is not None]
    if kept_sessions:
        max_ended_at = max(s.ended_at for s in kept_sessions)

        stmt = (
            insert(TrackerSyncState)
            .values(
                user_id=device.user_id,
                device_id=device.device_id,
                last_synced_at=max_ended_at,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["user_id", "device_id"],
                set_={
                    "last_synced_at": max_ended_at,
                    "updated_at": datetime.now(timezone.utc),
                },
                where=TrackerSyncState.last_synced_at < max_ended_at,
            )
        )
        db.execute(stmt)

    db.commit()

    return {
        "accepted": result.accepted,
        "duplicate": result.duplicate,
        "invalid": result.invalid,
        "total": len(result.results),
    }
