from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.entries.models import Entry, EntryStatus
from app.tracker_sync.models import LocalSession

UPSERT_FIELDS = ("bundle_id", "app_name", "window_title", "started_at", "ended_at", "end_reason", "is_idle")


def upsert_sessions(db: Session, rows: list[dict]) -> tuple[set[UUID], set[UUID]]:
    """Save a batch of tracker sessions using an "upsert" (insert if new, update if it already exists).

    If a session matching (user_id, id) already exists, all of its mutable fields (bundle_id,
    app_name, window_title, started_at, ended_at, end_reason, is_idle) are updated. This allows
    sessions to be re-sent with corrected information after they finish, ensuring the database
    holds the latest version rather than dropping new info.

    Returns (inserted_ids, conflicted_ids):
      - inserted_ids: set of UUIDs for newly inserted sessions.
      - conflicted_ids: set of UUIDs for existing sessions that were updated.

    Under the hood, `xmax = 0` is used as a simple way to ask Postgres whether each row was
    brand new or if it already existed and got updated, following the combined insert-or-update operation.
    """
    if not rows:
        return set(), set()
    insert_stmt = insert(LocalSession).values(rows)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["user_id", "id"],
        set_={
            **{field: getattr(insert_stmt.excluded, field) for field in UPSERT_FIELDS},
            "synced_at": func.now(),
        },
        where=or_(*[
            LocalSession.__table__.c[field].is_distinct_from(getattr(insert_stmt.excluded, field))
            for field in UPSERT_FIELDS
        ]),
    ).returning(LocalSession.id, literal_column("(xmax = 0)").label("inserted"))
    result = db.execute(stmt)

    inserted_ids: set[UUID] = set()
    conflicted_ids: set[UUID] = set()
    for row in result:
        (inserted_ids if row.inserted else conflicted_ids).add(row.id)
    return inserted_ids, conflicted_ids


def get_sessions_synced_before(db: Session, cutoff: datetime) -> list[LocalSession]:
    return db.query(LocalSession).filter(LocalSession.synced_at < cutoff).all()


def get_approved_entry_dates(db: Session, user_id: int) -> set[date]:
    """Find which specific calendar dates already have a finished, approved work log entry.

    Uses `work_date` -- the day the entry's content is actually ABOUT -- not `created_at` (when
    the row was inserted/approved). Those two commonly diverge (e.g. work done Monday, approved
    Friday), and keying off `created_at` would both make Monday's raw data un-matchable and risk
    an unrelated day matching by coincidence.

    This date set is used later to decide whether it is safe to clean up old raw session data
    for those dates.
    """
    rows = (
        db.query(Entry.work_date)
        .filter(Entry.user_id == user_id, Entry.status == EntryStatus.approved)
        .all()
    )
    return {row[0] for row in rows}


def delete_sessions(db: Session, user_id: int, session_ids: list[UUID]) -> int:
    if not session_ids:
        return 0
    result = db.execute(
        delete(LocalSession).where(LocalSession.user_id == user_id, LocalSession.id.in_(session_ids))
    )
    db.commit()
    return result.rowcount
