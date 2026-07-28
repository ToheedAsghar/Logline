from datetime import datetime

from sqlalchemy.orm import Session

from app.timeline.models import ConfidenceLevel, Event


def get_owned_event(db: Session, event_id: int, user_id: int) -> Event | None:
    return db.query(Event).filter(Event.id == event_id, Event.user_id == user_id).first()


def list_events_in_range(db: Session, user_id: int, start: datetime, end: datetime) -> list[Event]:
    return (
        db.query(Event)
        .filter(Event.user_id == user_id, Event.timestamp >= start, Event.timestamp <= end)
        .order_by(Event.timestamp.asc())
        .all()
    )


def update_event(
    db: Session,
    event: Event,
    *,
    timestamp: datetime | None,
    metadata_patch: dict,
    confidence: ConfidenceLevel | None,
) -> Event:
    if timestamp is not None:
        event.timestamp = timestamp
    if metadata_patch:
        # Reassign the whole dict (rather than mutate in place) so
        # SQLAlchemy's change tracking picks up the JSONB update.
        event.event_metadata = {**(event.event_metadata or {}), **metadata_patch}
    if confidence is not None:
        event.confidence = confidence
    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session, event: Event) -> None:
    db.delete(event)
    db.commit()
