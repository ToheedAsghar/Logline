"""Core business logic for processing and ingesting raw tracker sessions.

This module processes parsed session data (LocalSessionIn) regardless of how it arrived (e.g., HTTP request or
file upload). It handles validating session records, checking for duplicates, and saving valid records to the database.

Database cleanup for old sessions lives separately in `app.tracker_sync.retention` to ensure the ingestion workflow
can never accidentally trigger data deletion.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy.orm import Session

from app.tracker_sync import crud
from app.tracker_sync.constants import (
    CLOCK_SKEW_TOLERANCE_MINUTES, KNOWN_END_REASONS, MAX_SESSION_DURATION_HOURS, REASON_BLANK_END_REASON,
    REASON_DUPLICATE_IN_BATCH, REASON_ENDED_BEFORE_STARTED, REASON_ENDED_IN_FUTURE, REASON_EXCEEDS_MAX_DURATION,
    REASON_MISSING_TIMEZONE, REASON_SESSION_UPDATED, REASON_UNCLOSED_SESSION,
)
from app.tracker_sync.schemas import LocalSessionIn

logger = logging.getLogger(__name__)


class IngestStatus(str, Enum):
    accepted = "accepted"
    duplicate = "duplicate"
    invalid = "invalid"


@dataclass
class IngestRowResult:
    id: UUID
    status: IngestStatus
    reason: str | None = None


@dataclass
class IngestResult:
    results: list[IngestRowResult] = field(default_factory=list)

    @property
    def accepted(self) -> int:
        return sum(1 for r in self.results if r.status is IngestStatus.accepted)

    @property
    def duplicate(self) -> int:
        return sum(1 for r in self.results if r.status is IngestStatus.duplicate)

    @property
    def invalid(self) -> int:
        return sum(1 for r in self.results if r.status is IngestStatus.invalid)


def _to_utc(value: datetime | None) -> datetime | None:
    """Convert a timestamp to UTC.

    Returns None if the value is missing, or if the timestamp has no timezone information attached, as timestamps
    without timezones are ambiguous and cannot be processed safely.
    """
    if value is None or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _invalid_reason(
    session: LocalSessionIn, now: datetime, started_at_utc: datetime | None, ended_at_utc: datetime | None
) -> str | None:
    """Check if a session record has invalid or missing data.

    `started_at_utc`/`ended_at_utc` are the already-UTC-normalized timestamps (see `_to_utc`), computed once by the
    caller and reused for persistence via `_row_dict` -- so validation and the row actually written always agree
    on the same normalized values.

    Returns a human-readable rejection reason string if the record is invalid, or None if the session is valid and
    ready to be processed. Note that unknown `end_reason` values are allowed and not flagged as invalid.
    """
    if session.ended_at is None or session.end_reason is None:
        return REASON_UNCLOSED_SESSION

    if not session.end_reason.strip():
        return REASON_BLANK_END_REASON

    if started_at_utc is None or ended_at_utc is None:
        return REASON_MISSING_TIMEZONE

    if ended_at_utc < started_at_utc:
        return REASON_ENDED_BEFORE_STARTED

    tolerance = timedelta(minutes=CLOCK_SKEW_TOLERANCE_MINUTES)
    if ended_at_utc > now + tolerance:
        return REASON_ENDED_IN_FUTURE

    if ended_at_utc - started_at_utc >= timedelta(hours=MAX_SESSION_DURATION_HOURS):
        return REASON_EXCEEDS_MAX_DURATION

    return None


def _row_dict(session: LocalSessionIn, user_id: int, started_at_utc: datetime, ended_at_utc: datetime) -> dict:
    """Convert a session schema object into a dictionary formatted for database insertion.

    Takes the same UTC-normalized `started_at`/`ended_at` that `_invalid_reason` validated, rather than the original
    un-normalized values, so what's persisted matches what was checked.
    """
    return {
        "id": session.id,
        "user_id": user_id,
        "bundle_id": session.bundle_id,
        "app_name": session.app_name,
        "window_title": session.window_title,
        "project_path": session.project_path,
        "context_detail": session.context_detail,
        "started_at": started_at_utc,
        "ended_at": ended_at_utc,
        "end_reason": session.end_reason,
        "is_idle": session.is_idle,
    }


def ingest_sessions(
    db: Session,
    user_id: int,
    sessions: list[LocalSessionIn],
    schema_version: str | None = None,
) -> IngestResult:
    """Validate and save a batch of tracker sessions for a single user.

    Process details:
    - Only completed sessions (having both `ended_at` and `end_reason`) are accepted. Still-open sessions are skipped
      until they are finished by the tracker.
    - Valid sessions are saved using an "upsert" (inserted if new, updated if existing). Updating existing records
      ensures corrected session details re-sent by the tracker are updated rather than ignored.
    - Any `end_reason` value is accepted. Unrecognized reasons log a warning but are still saved to prevent data
      loss if new reason types are added in future tracker updates.

    Returns:
        IngestResult: A detailed summary for each session in the batch, marking each row as 'accepted' (newly
        inserted), 'duplicate' (already existing, so updated), or 'invalid' (rejected). If the same session ID
        appears multiple times in a single batch, only the latest one is written and earlier ones are marked as
        duplicates.
    """
    if schema_version is not None:
        logger.info(
            "tracker_sync.ingest_sessions: schema_version=%r for user_id=%s (%d sessions)",
            schema_version, user_id, len(sessions),
        )

    now = datetime.now(timezone.utc)
    results: list[IngestRowResult | None] = [None] * len(sessions)
    winning_index_for_id: dict[UUID, int] = {}
    normalized_by_index: dict[int, tuple[datetime, datetime]] = {}

    for index, session in enumerate(sessions):
        started_at_utc = _to_utc(session.started_at)
        ended_at_utc = _to_utc(session.ended_at)
        reason = _invalid_reason(session, now, started_at_utc, ended_at_utc)
        if reason is not None:
            results[index] = IngestRowResult(id=session.id, status=IngestStatus.invalid, reason=reason)
            continue
        normalized_by_index[index] = (started_at_utc, ended_at_utc)

        if session.end_reason not in KNOWN_END_REASONS:
            logger.warning(
                "tracker_sync.ingest_sessions: unknown end_reason %r for id=%s user_id=%s -- storing as free text",
                session.end_reason, session.id, user_id,
            )

        prior_index = winning_index_for_id.get(session.id)
        if prior_index is not None:
            results[prior_index] = IngestRowResult(
                id=session.id, status=IngestStatus.duplicate, reason=REASON_DUPLICATE_IN_BATCH
            )
        winning_index_for_id[session.id] = index

    valid_rows = [
        _row_dict(sessions[index], user_id, *normalized_by_index[index])
        for index in winning_index_for_id.values()
    ]
    inserted_ids, _conflicted_ids = crud.upsert_sessions(db, valid_rows)

    for session_id, index in winning_index_for_id.items():
        if session_id in inserted_ids:
            results[index] = IngestRowResult(id=session_id, status=IngestStatus.accepted)
        else:
            results[index] = IngestRowResult(
                id=session_id, status=IngestStatus.duplicate, reason=REASON_SESSION_UPDATED
            )

    return IngestResult(results=[r for r in results if r is not None])
