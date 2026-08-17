"""Deletion of old refresh-token session rows.

Rows are deleted based on `expires_at`, never `revoked_at`. A revoked row must be kept until it expires so the
server can detect and stop stolen tokens being replayed. Once `expires_at` plus the retention window passes,
the expired token can no longer authenticate anything and the row is safe to delete.

The cutoff is computed by the database (`now()`), not the app server's clock, unlike the reuse-detection grace
comparison in `crud.py`. That difference is deliberate, not an oversight: a fast app clock here computes a cutoff
that is actually in the future and mass-deletes every live session in the table -- an unbounded, one-directional
failure with no fail-safe side. The grace comparison in `crud.py` has no such asymmetry (a skewed clock there only
ever widens a 10-second benign-replay window, never causes a wrongful revoke), which is why that check is allowed
to stay on the app clock and this one is not.
"""

import time

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.types import DateTime, Interval

from app.auth.constants import (
    SESSION_PURGE_BATCH_PAUSE_SECONDS, SESSION_PURGE_BATCH_SIZE, SESSION_RETENTION_WINDOW_DAYS,
)
from app.auth.models import UserSession


def _cutoff_expression():
    """A SQL expression for `now() - <retention window>`, evaluated by Postgres rather than the app server."""
    window = func.cast(f"{SESSION_RETENTION_WINDOW_DAYS} days", Interval)
    return func.now(type_=DateTime(timezone=True)) - window


def count_purgeable_sessions(db: Session) -> int:
    """How many rows `purge_expired_sessions` would delete right now, without deleting anything."""
    return db.execute(
        select(func.count()).select_from(UserSession).where(UserSession.expires_at < _cutoff_expression())
    ).scalar_one()


def purge_expired_sessions(db: Session, *, batch_size: int = SESSION_PURGE_BATCH_SIZE) -> int:
    """Deletes session rows that expired more than `SESSION_RETENTION_WINDOW_DAYS` ago. Returns the number deleted.

    Deletes in small batches with brief pauses between them rather than one large delete. This avoids holding database
    table locks for too long and prevents write spikes on a table that grows continuously with every token refresh.
    """
    deleted = 0

    while True:
        doomed = (
            select(UserSession.id)
            .where(UserSession.expires_at < _cutoff_expression())
            .limit(batch_size)
            .scalar_subquery()
        )
        batch = db.execute(delete(UserSession).where(UserSession.id.in_(doomed))).rowcount
        db.commit()
        deleted += batch

        if batch < batch_size:
            return deleted
        time.sleep(SESSION_PURGE_BATCH_PAUSE_SECONDS)
