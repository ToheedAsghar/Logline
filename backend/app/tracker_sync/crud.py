from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.entries.models import Entry, EntryStatus
from app.tracker_sync.models import LocalSession, TrackerDevice, TrackerSyncState
from app.tracker_sync.security import generate_device_token, hash_device_token

UPSERT_FIELDS = (
    "bundle_id",
    "app_name",
    "window_title",
    "project_path",
    "context_detail",
    "started_at",
    "ended_at",
    "end_reason",
    "is_idle",
)


def upsert_sessions(db: Session, rows: list[dict]) -> tuple[set[UUID], set[UUID]]:
    """Save a batch of tracker sessions using an "upsert" (insert if new, update if it already exists).

    If a session matching (user_id, id) already exists, all of its mutable fields (bundle_id,
    app_name, window_title, project_path, context_detail, started_at, ended_at, end_reason,
    is_idle) are updated. This allows sessions to be re-sent with corrected information after
    they finish, ensuring the database holds the latest version rather than dropping new info.

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


def create_device(db: Session, user_id: int, name: str) -> tuple[TrackerDevice, str]:
    """Enroll a new tracker device, returning it alongside the plaintext token.

    Only the token's hash is stored, so this return value is the only chance anything has to see it.
    """
    token = generate_device_token()
    device = TrackerDevice(
        user_id=user_id,
        device_id=uuid4(),
        name=name,
        token_hash=hash_device_token(token),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device, token


def get_device_by_token(db: Session, token: str) -> TrackerDevice | None:
    """Look a device up by the hash of its presented token. Returns None for an unknown token and for a device that
    cannot authenticate (revoked, or predating the hashed-token scheme) -- callers must not distinguish the two."""
    device = db.query(TrackerDevice).filter(TrackerDevice.token_hash == hash_device_token(token)).first()
    if device is None or not device.is_active:
        return None
    return device


def revoke_device(db: Session, user_id: int, device_id: UUID) -> TrackerDevice | None:
    """Mark a device revoked, scoped to its owner so one user can never revoke another's device. Returns None if
    no such device belongs to this user.

    Idempotent: revoking an already-revoked device keeps the original timestamp. The row and its sync checkpoint
    are kept, so a re-enrolled machine does not resync from scratch.
    """
    device = (
        db.query(TrackerDevice)
        .filter(TrackerDevice.user_id == user_id, TrackerDevice.device_id == device_id)
        .first()
    )
    if device is None:
        return None
    if device.revoked_at is None:
        device.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(device)
    return device


def get_sync_status(db: Session, user_id: int) -> tuple[datetime | None, int]:
    """Returns (newest checkpoint across the user's active devices, count of those devices). Revoked devices are
    excluded from both, so a retired machine's stale checkpoint cannot keep an account looking freshly synced."""
    active_device_ids = db.query(TrackerDevice.device_id).filter(
        TrackerDevice.user_id == user_id,
        TrackerDevice.revoked_at.is_(None),
        TrackerDevice.token_hash.isnot(None),
    )
    last_synced_at = (
        db.query(func.max(TrackerSyncState.last_synced_at))
        .filter(
            TrackerSyncState.user_id == user_id,
            TrackerSyncState.device_id.in_(active_device_ids),
        )
        .scalar()
    )
    device_count = active_device_ids.count()
    return last_synced_at, device_count


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
