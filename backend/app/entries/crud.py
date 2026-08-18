from datetime import datetime

from sqlalchemy.orm import Session

from app.entries.models import Entry, EntryFormat, EntryStatus, EntryVersion, EntryVersionSource


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
    db: Session, entry: Entry, *, content: dict | None, status: EntryStatus | None, approved_at: datetime | None,
) -> Entry:
    """Apply partial updates to an entry and commit.

    If ``content`` is changed on an already-approved entry, appends a ``human_revision`` EntryVersion snapshot so
    the prior approved content is recoverable from the append-only history. Edits to draft or pending entries do not
    create a version row — only generation (ai_draft) and post-approval moments are tracked.
    """
    if entry.status == EntryStatus.discarded:
        raise ValueError("Discarded entries cannot be changed")
    if entry.reconciliation_draft_id is not None:
        if entry.status != EntryStatus.approved:
            raise ValueError("Unapproved reconciliation entries can only be changed through Save day")
        if status is not None or approved_at is not None:
            raise ValueError("Approved reconciliation lifecycle fields cannot be changed")

    is_post_approval_edit = content is not None and entry.status == EntryStatus.approved

    if content is not None:
        entry.content = content
    if status is not None:
        entry.status = status
    if approved_at is not None:
        entry.approved_at = approved_at
    if is_post_approval_edit:
        db.add(EntryVersion(entry_id=entry.id, source=EntryVersionSource.human_revision, content=entry.content))
    db.commit()
    db.refresh(entry)
    return entry


def approve_entry(db: Session, entry: Entry, approved_at: datetime) -> Entry:
    """Mark an entry as approved and record the moment in the append-only version history.

    Always appends a ``human_approved`` EntryVersion snapshot holding the entry's current content at approval time.
    """
    if entry.status == EntryStatus.discarded:
        raise ValueError("Discarded entries cannot be approved")
    if entry.reconciliation_draft_id is not None:
        raise ValueError("Reconciliation entries can only be approved through Save day")

    entry.status = EntryStatus.approved
    entry.approved_at = approved_at
    db.add(EntryVersion(entry_id=entry.id, source=EntryVersionSource.human_approved, content=entry.content))
    db.commit()
    db.refresh(entry)
    return entry
