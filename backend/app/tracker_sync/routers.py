from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.auth.deps import get_tracker_user
from app.auth.models import User
from app.db.session import get_db
from app.tracker_sync import service
from app.tracker_sync.models import TrackerDevice, TrackerSyncState
from app.tracker_sync.schemas import SyncPayload

router = APIRouter(prefix="/tracker", tags=["tracker"])


class CheckpointResponse(BaseModel):
    last_synced_at: datetime | None


@router.get("/sync/checkpoint", response_model=CheckpointResponse)
def get_sync_checkpoint(
    device_id: UUID,
    user: User = Depends(get_tracker_user),
    db: Session = Depends(get_db),
):
    """Get the high-water mark for a specific tracker device to avoid re-syncing old data."""
    state = (
        db.query(TrackerSyncState)
        .filter(
            TrackerSyncState.user_id == user.id,
            TrackerSyncState.device_id == device_id,
        )
        .first()
    )
    return CheckpointResponse(last_synced_at=state.last_synced_at if state else None)


@router.post("/sync")
def sync_sessions(
    payload: SyncPayload,
    user: User = Depends(get_tracker_user),
    db: Session = Depends(get_db),
):
    """Sync a batch of local tracker sessions to the backend database.
    
    This performs an idempotent upsert, so retrying the same batch is safe.
    Updates the sync checkpoint automatically based on the latest ended_at timestamp
    in the processed batch.
    """
    device = db.query(TrackerDevice).filter(
        TrackerDevice.device_id == payload.device_id,
        TrackerDevice.user_id == user.id,
    ).first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device not registered to this user",
        )

    result = service.ingest_sessions(db, user_id=user.id, sessions=payload.sessions)

    valid_sessions = [s for s in payload.sessions if s.ended_at is not None]
    if valid_sessions:
        max_ended_at = max(s.ended_at for s in valid_sessions)
        
        # Upsert the checkpoint
        stmt = insert(TrackerSyncState).values(
            user_id=user.id,
            device_id=payload.device_id,
            last_synced_at=max_ended_at,
            updated_at=datetime.now(timezone.utc)
        ).on_conflict_do_update(
            index_elements=["user_id", "device_id"],
            set_={
                "last_synced_at": max_ended_at,
                "updated_at": datetime.now(timezone.utc)
            },
            where=TrackerSyncState.last_synced_at < max_ended_at
        )
        db.execute(stmt)

    db.commit()

    return {
        "accepted": result.accepted,
        "duplicate": result.duplicate,
        "invalid": result.invalid,
        "total": len(result.results),
    }
