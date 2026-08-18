from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.entries import crud
from app.entries.models import Entry, EntryFormat, EntryStatus
from app.entries.schemas import EntryResponse, EntryUpdate

router = APIRouter(prefix="/entries", tags=["entries"])

ENTRY_NOT_FOUND_ERROR = "Entry not found"


def _get_owned_entry(entry_id: int, current_user: User, db: Session) -> Entry:
    """Fetch an entry scoped to `current_user`, or raise 404.

    Ownership is filtered in the query itself, not checked after fetching, so an entry owned by
    someone else 404s exactly like one that doesn't exist -- existence isn't a hint to leak. See
    backend/CLAUDE.md's error convention.
    """
    entry = crud.get_owned_entry(db, entry_id, current_user.id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ENTRY_NOT_FOUND_ERROR)
    return entry


def _reject_reconciliation_lifecycle_entry(entry: Entry, *, allow_approved_revision: bool = False) -> None:
    if entry.status == EntryStatus.discarded:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This entry was discarded with its reconciliation draft and can no longer be changed.",
        )
    if entry.reconciliation_draft_id is not None and not (
        allow_approved_revision and entry.status == EntryStatus.approved
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This entry is controlled by its reconciliation draft. Use Save day to apply reviewed changes.",
        )


@router.get("", response_model=list[EntryResponse])
def list_entries(
    status_filter: EntryStatus | None = Query(default=None, alias="status"),
    format: EntryFormat | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return crud.list_entries_for_user(db, current_user.id, status=status_filter, format=format)


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
    _reject_reconciliation_lifecycle_entry(entry, allow_approved_revision=True)
    if entry.reconciliation_draft_id is not None and (payload.status is not None or payload.approved_at is not None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approved reconciliation lifecycle fields cannot be changed through the generic entry API.",
        )

    try:
        payload = payload.validate_content_for(entry.format)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return crud.update_entry(
        db, entry, content=payload.content, status=payload.status, approved_at=payload.approved_at
    )


@router.post("/{entry_id}/approve", response_model=EntryResponse)
def approve_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = _get_owned_entry(entry_id, current_user, db)
    _reject_reconciliation_lifecycle_entry(entry)
    return crud.approve_entry(db, entry, datetime.now(timezone.utc))
