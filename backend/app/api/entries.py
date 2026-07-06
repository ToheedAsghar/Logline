from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.entry import Entry, EntryFormat, EntryStatus
from app.models.user import User
from app.schemas.entry import EntryResponse, EntryUpdate

router = APIRouter(prefix="/entries", tags=["entries"])


def _get_owned_entry(entry_id: int, current_user: User, db: Session) -> Entry:
    # Scoped by user_id in the query itself (not checked after fetching) so an
    # entry owned by someone else 404s exactly like one that doesn't exist —
    # existence isn't a hint we want to leak. See CLAUDE.md's error convention.
    entry = db.query(Entry).filter(Entry.id == entry_id, Entry.user_id == current_user.id).first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    return entry


@router.get("", response_model=list[EntryResponse])
def list_entries(
    status_filter: EntryStatus | None = Query(default=None, alias="status"),
    format: EntryFormat | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Entry).filter(Entry.user_id == current_user.id)
    if status_filter is not None:
        query = query.filter(Entry.status == status_filter)
    if format is not None:
        query = query.filter(Entry.format == format)
    return query.order_by(Entry.created_at.desc()).all()


@router.get("/{entry_id}", response_model=EntryResponse)
def get_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_entry(entry_id, current_user, db)


@router.patch("/{entry_id}", response_model=EntryResponse)
def update_entry(
    entry_id: int,
    payload: EntryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = _get_owned_entry(entry_id, current_user, db)

    try:
        payload = payload.validate_content_for(entry.format)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if payload.content is not None:
        entry.content = payload.content
    if payload.status is not None:
        entry.status = payload.status
    if payload.approved_at is not None:
        entry.approved_at = payload.approved_at

    db.commit()
    db.refresh(entry)
    return entry


@router.post("/{entry_id}/approve", response_model=EntryResponse)
def approve_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = _get_owned_entry(entry_id, current_user, db)
    entry.status = EntryStatus.approved
    entry.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entry)
    return entry
