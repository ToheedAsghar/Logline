from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.timeline import crud
from app.timeline.models import Event
from app.timeline.schemas import EventResponse, EventUpdate

router = APIRouter(prefix="/timeline", tags=["timeline"])


def _get_owned_event(event_id: int, current_user: User, db: Session) -> Event:
    # Scoped by user_id in the query itself, same convention as
    # `_get_owned_entry` in `app/entries/routers.py` -- an event owned by
    # someone else 404s exactly like one that doesn't exist.
    event = crud.get_owned_event(db, event_id, current_user.id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


@router.get("", response_model=list[EventResponse])
def get_timeline(
    start: datetime = Query(...),
    end: datetime = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return crud.list_events_in_range(db, current_user.id, start, end)


@router.patch("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    payload: EventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = _get_owned_event(event_id, current_user, db)

    metadata_patch = {}
    if payload.title is not None:
        metadata_patch["title"] = payload.title
    if payload.summary is not None:
        metadata_patch["summary"] = payload.summary
    if payload.end_timestamp is not None:
        metadata_patch["end_timestamp"] = payload.end_timestamp.isoformat()

    return crud.update_event(
        db, event, timestamp=payload.timestamp, metadata_patch=metadata_patch, confidence=payload.confidence
    )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = _get_owned_event(event_id, current_user, db)
    crud.delete_event(db, event)
