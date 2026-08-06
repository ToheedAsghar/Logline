"""REST surface for the Stage 4-6 reconciliation pipeline.

Two endpoints, deliberately split around the human:

- `POST /reconciliation/generate` gathers evidence, runs the model, verifies the draft, and returns it.
  It writes nothing. A draft is a proposal, and proposals do not belong in the entry history.
- `POST /reconciliation/approve` takes the draft a human actually approved and turns it into entries.

`approve` re-derives the evidence from the database and re-runs `verify_draft` against the submitted
draft rather than trusting the caller. The client is free to edit a draft before approving it, so the
draft arriving here is not the one `generate` returned and its verification result cannot be carried
over from that call. Re-verifying is what keeps an edited draft from charging more minutes than were
measured. Each approved entry gets a `human_approved` version snapshot in the same transaction, so
the approval is atomic across the whole draft -- a mid-loop failure rolls back every entry, not just
the one that failed.
"""

import logging
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent.llm import get_llm_provider
from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.reconciler import ReconciliationResult, reconcile_evidence
from app.agent.reconciliation.schemas import WorkLogDraft
from app.agent.reconciliation.verifier import verify_draft
from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.entries.models import Entry, EntryFormat, EntryStatus, EntryVersion, EntryVersionSource
from app.entries.schemas import EntryResponse, normalize_entry_content
from app.local_activity.aggregation import RawSessionRow, aggregate_local_activity
from app.matching.matcher import MatchResult, RemoteEventData, ResolvedLocalBlock, match_local_blocks_to_remote_events
from app.matching.models import RemoteEvent
from app.matching.resolution import resolve_project_identities
from app.tracker_sync.models import LocalSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])

MAX_RANGE_DAYS = 31


class ReconciliationDateRange(BaseModel):
    """Inclusive day range to reconcile, in the user's own terms."""

    date_range_start: date
    date_range_end: date

    @model_validator(mode="after")
    def _validate_range(self) -> "ReconciliationDateRange":
        if self.date_range_start > self.date_range_end:
            raise ValueError("date_range_start must be on or before date_range_end")
        if (self.date_range_end - self.date_range_start).days > MAX_RANGE_DAYS:
            raise ValueError(f"date range cannot span more than {MAX_RANGE_DAYS} days")
        return self

    def as_utc_bounds(self) -> tuple[datetime, datetime]:
        return (
            datetime.combine(self.date_range_start, time.min, tzinfo=timezone.utc),
            datetime.combine(self.date_range_end, time.max, tzinfo=timezone.utc),
        )


class ReconciliationApproveRequest(ReconciliationDateRange):
    """A human-approved draft, plus the range it covers so its evidence can be re-derived.

    The range is required rather than inferred from the draft's entry dates: verification checks that
    every *measured* block is accounted for, including blocks the draft assigned to nothing, and those
    blocks leave no trace in the draft to infer a range from.
    """

    draft: WorkLogDraft


def _gather_evidence(db: Session, user_id: int, start_dt: datetime, end_dt: datetime) -> MatchResult:
    """Run Stages 3-4 for one user and range: read stored evidence, then match local work to remote events.

    Reads only. Remote events are whatever `remote_events` already holds -- populating that table is the
    fetch pipeline's job, not this endpoint's, so reconciliation reports on the evidence that exists
    rather than silently depending on a live fetch succeeding.
    """
    remote_events = [
        RemoteEventData(
            external_id=row.external_id,
            source=row.source.value,
            remote_project_id=row.remote_project_id,
            occurred_at=row.occurred_at,
            event_type=row.event_type,
            summary=row.summary,
        )
        for row in (
            db.query(RemoteEvent)
            .filter(
                RemoteEvent.user_id == user_id,
                RemoteEvent.occurred_at >= start_dt,
                RemoteEvent.occurred_at <= end_dt,
            )
            .order_by(RemoteEvent.occurred_at.asc(), RemoteEvent.external_id.asc())
            .all()
        )
    ]

    sessions = (
        db.query(LocalSession)
        .filter(
            LocalSession.user_id == user_id,
            LocalSession.started_at < end_dt,
            LocalSession.ended_at > start_dt,
            LocalSession.is_idle.is_(False),
            LocalSession.project_path.isnot(None),
        )
        .order_by(LocalSession.started_at.asc(), LocalSession.id.asc())
        .all()
    )

    blocks = aggregate_local_activity(
        [
            RawSessionRow(
                project=session.project_path,
                app=session.app_name,
                start_time=session.started_at,
                end_time=session.ended_at,
            )
            for session in sessions
        ]
    )

    identity_cache: dict[str, dict[str, str | None]] = {}
    resolved = []
    for block in blocks:
        if block.project not in identity_cache:
            identity_cache[block.project] = resolve_project_identities(db, user_id, block.project)
        resolved.append(ResolvedLocalBlock(block=block, remote_identities=identity_cache[block.project]))

    return match_local_blocks_to_remote_events(resolved, remote_events)


@router.post("/generate", response_model=ReconciliationResult)
async def generate_reconciliation(
    payload: ReconciliationDateRange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReconciliationResult:
    """Reconcile the authenticated user's stored evidence for a date range into a draft work log.

    Returns the draft together with its verification result and persists nothing. A failing
    verification still returns 200 with the draft -- a flagged draft is exactly what a human needs
    to see, so withholding it would defeat the point of the review step.
    """
    start_dt, end_dt = payload.as_utc_bounds()
    match_result = await run_in_threadpool(_gather_evidence, db, current_user.id, start_dt, end_dt)

    return await reconcile_evidence(
        matched_groups=match_result.matched,
        unmatched_blocks=match_result.unmatched_blocks,
        unmatched_events=match_result.unmatched_events,
        llm_provider=get_llm_provider(),
        tz=timezone.utc,
    )


def _entry_content(draft_entry) -> dict:
    """Build the stored content for one approved draft entry.

    Keeps the allocations, tag and cited event ids alongside the prose. Storing only the description
    would discard the link between an entry and the measured time it was charged against, leaving an
    approved entry impossible to audit against its evidence afterwards.
    """
    return normalize_entry_content(
        EntryFormat.project_log,
        {
            "text": draft_entry.description,
            "project": draft_entry.project,
            "tag": draft_entry.tag.value,
            "allocations": [{"block_id": a.block_id, "minutes": a.minutes} for a in draft_entry.allocations],
            "source_remote_event_ids": draft_entry.source_remote_event_ids,
            "review_reason": draft_entry.review_reason,
        },
    )


@router.post("/approve", response_model=list[EntryResponse], status_code=status.HTTP_201_CREATED)
async def approve_reconciliation(
    payload: ReconciliationApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Entry]:
    """Persist a human-approved draft as approved entries, after re-verifying it against the evidence.

    Rejects the whole draft with 422 if verification finds any error-severity issue. Partial writes are
    not offered: the checks are about time conservation across the draft as a whole, so accepting the
    entries that happen to pass individually could still persist a double-charged block.

    Reminders and `residual_unassigned_minutes` are intentionally not persisted -- a reminder is a
    question about missing evidence and residual minutes are time explicitly assigned to nothing;
    neither is a work-log entry.
    """
    start_dt, end_dt = payload.as_utc_bounds()
    match_result = await run_in_threadpool(_gather_evidence, db, current_user.id, start_dt, end_dt)

    evidence = build_evidence(
        matched_groups=match_result.matched,
        unmatched_blocks=match_result.unmatched_blocks,
        unmatched_events=match_result.unmatched_events,
        tz=timezone.utc,
    )

    verification = verify_draft(payload.draft, evidence)
    if not verification.passed:
        logger.warning(
            "Rejected reconciliation approval for user %s: %s error(s)",
            current_user.id,
            sum(1 for issue in verification.issues if issue.severity == "error"),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Draft failed verification against its evidence and was not saved.",
                "issues": [issue.model_dump() for issue in verification.issues],
            },
        )

    approved_at = datetime.now(timezone.utc)
    entries: list[Entry] = []
    for draft_entry in payload.draft.entries:
        entry = Entry(
            user_id=current_user.id,
            format=EntryFormat.project_log,
            content=_entry_content(draft_entry),
            work_date=draft_entry.date,
            status=EntryStatus.approved,
            approved_at=approved_at,
        )
        db.add(entry)
        db.flush()
        db.add(EntryVersion(entry_id=entry.id, source=EntryVersionSource.human_approved, content=entry.content))
        entries.append(entry)

    db.commit()
    for entry in entries:
        db.refresh(entry)

    return entries
