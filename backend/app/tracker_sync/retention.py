"""Data cleanup and retention rules for raw tracker sessions.

This module handles removing old raw session data to protect user privacy.
The main copy of tracker activity lives locally on the user's computer, so raw data
is only kept on the server for a limited time.

Key design points:
- Separate from Ingestion: Cleanup is deliberately kept in this separate module so that
  normal data ingestion code cannot accidentally trigger session deletions. Cleanup should
  only be run by a scheduled background job or manual admin command.
- Reconciled Days Only: Sessions are only deleted if they belong to a day that has an
  approved work log entry. Unreconciled days are never deleted, no matter how old they are.

Known limitation -- UTC calendar days, not the user's local day: there is no per-user timezone
setting anywhere in the codebase yet, so "which day" a session belongs to is computed by
normalizing to UTC and taking that date. For a user far from UTC, a late-evening (or early-
morning) session can land on a different calendar day locally than it does here, occasionally
causing a session near midnight-UTC to be reconciled/retained a day off from what the user would
expect. Revisit once user-level timezone storage exists (see app/auth/models.py::User); until
then, UTC is the interim approach everywhere in this module.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.tracker_sync import crud
from app.tracker_sync.constants import RETENTION_WINDOW_DAYS


def cleanup_synced_sessions(db: Session) -> int:
    """Delete old raw tracker sessions that have already been finalized into approved work logs.

    A session row is deleted only if:
    1. It is older than RETENTION_WINDOW_DAYS, AND
    2. The date it occurred on has an approved work log entry for that user.

    Sessions on days without approved work logs are kept indefinitely. Checks are done per user
    so one user's approved work logs will never cause another user's sessions to be deleted.

    Returns:
        int: The total number of deleted session rows.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS)
    candidates = crud.get_sessions_synced_before(db, cutoff)

    approved_dates_by_user: dict[int, set[date]] = {}
    to_delete_by_user: dict[int, list[UUID]] = {}

    for session in candidates:
        if session.user_id not in approved_dates_by_user:
            approved_dates_by_user[session.user_id] = crud.get_approved_entry_dates(db, session.user_id)
        # Normalized explicitly rather than relying on whatever tzinfo the DB driver
        # happens to hand back (session timezone config can vary) -- see the module
        # docstring's "known limitation" note on UTC-vs-user-local calendar days.
        started_at_utc_date = session.started_at.astimezone(timezone.utc).date()
        if started_at_utc_date in approved_dates_by_user[session.user_id]:
            to_delete_by_user.setdefault(session.user_id, []).append(session.id)

    deleted = 0
    for uid, ids in to_delete_by_user.items():
        deleted += crud.delete_sessions(db, uid, ids)
    return deleted
