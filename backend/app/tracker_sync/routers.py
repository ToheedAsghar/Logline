from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.deps import get_tracker_device
from app.db.session import get_db
from app.tracker_sync import service
from app.tracker_sync.constants import DEVICE_MISMATCH_ERROR_MSG
from app.tracker_sync.models import TrackerDevice, TrackerSyncState
from app.tracker_sync.schemas import SyncPayload

router = APIRouter(prefix="/tracker", tags=["tracker"])


class CheckpointResponse(BaseModel):
    last_synced_at: datetime | None


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
    return CheckpointResponse(last_synced_at=state.last_synced_at if state else None)


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

        # Upsert the checkpoint
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
