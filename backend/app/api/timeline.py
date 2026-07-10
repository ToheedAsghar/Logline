from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.event import Event
from app.models.user import User
from app.schemas.event import EventResponse, EventUpdate

router = APIRouter(prefix="/timeline", tags=["timeline"])


def _get_owned_event(event_id: int, current_user: User, db: Session) -> Event:
    # Scoped by user_id in the query itself, same convention as
    # `_get_owned_entry` in `app/api/entries.py` -- an event owned by someone
    # else 404s exactly like one that doesn't exist.
    event = db.query(Event).filter(Event.id == event_id, Event.user_id == current_user.id).first()
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
    return (
        db.query(Event)
        .filter(Event.user_id == current_user.id, Event.timestamp >= start, Event.timestamp <= end)
        .order_by(Event.timestamp.asc())
        .all()
    )


@router.patch("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    payload: EventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = _get_owned_event(event_id, current_user, db)

    if payload.timestamp is not None:
        event.timestamp = payload.timestamp

    metadata_patch = {}
    if payload.title is not None:
        metadata_patch["title"] = payload.title
    if payload.summary is not None:
        metadata_patch["summary"] = payload.summary
    if payload.end_timestamp is not None:
        metadata_patch["end_timestamp"] = payload.end_timestamp.isoformat()
    if metadata_patch:
        # Reassign the whole dict (rather than mutate in place) so
        # SQLAlchemy's change tracking picks up the JSONB update.
        event.event_metadata = {**(event.event_metadata or {}), **metadata_patch}

    if payload.confidence is not None:
        event.confidence = payload.confidence

    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = _get_owned_event(event_id, current_user, db)
    db.delete(event)
    db.commit()
