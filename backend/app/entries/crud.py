from datetime import datetime

from sqlalchemy.orm import Session

from app.entries.models import Entry, EntryFormat, EntryStatus


def list_entries_for_user(
    db: Session, user_id: int, *, status: EntryStatus | None = None, format: EntryFormat | None = None
) -> list[Entry]:
    query = db.query(Entry).filter(Entry.user_id == user_id)
    if status is not None:
        query = query.filter(Entry.status == status)
    if format is not None:
        query = query.filter(Entry.format == format)
    return query.order_by(Entry.created_at.desc()).all()


def get_owned_entry(db: Session, entry_id: int, user_id: int) -> Entry | None:
    return db.query(Entry).filter(Entry.id == entry_id, Entry.user_id == user_id).first()


def update_entry(
    db: Session,
    entry: Entry,
    *,
    content: dict | None,
    status: EntryStatus | None,
    approved_at: datetime | None,
) -> Entry:
    if content is not None:
        entry.content = content
    if status is not None:
        entry.status = status
    if approved_at is not None:
        entry.approved_at = approved_at
    db.commit()
    db.refresh(entry)
    return entry


def approve_entry(db: Session, entry: Entry, approved_at: datetime) -> Entry:
    entry.status = EntryStatus.approved
    entry.approved_at = approved_at
    db.commit()
    db.refresh(entry)
    return entry
