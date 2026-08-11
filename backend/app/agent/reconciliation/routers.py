"""Persist generated reconciliation drafts and atomically approve their reviewed working copies."""

import logging
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent.llm import get_llm_provider
from app.agent.reconciliation.constants import MAX_RANGE_DAYS
from app.agent.reconciliation.evidence import build_evidence, compute_tracked_wall_clock_minutes
from app.agent.reconciliation.models import ReconciliationDraft, ReconciliationDraftState
from app.agent.reconciliation.reconciler import reconcile_evidence
from app.agent.reconciliation.schemas import ReviewWorkLogDraft
from app.agent.reconciliation.verifier import VerificationResult, verify_draft
from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.timezones import resolve_timezone
from app.db.session import get_db
from app.entries.models import Entry, EntryFormat, EntryStatus, EntryVersion, EntryVersionSource
from app.entries.schemas import EntryResponse, normalize_entry_content
from app.local_activity.aggregation import (
    RawSessionRow, aggregate_local_activity, local_date, split_blocks_at_local_midnight,
)
from app.local_activity.classification import SessionCategory, classify_session, parse_context_detail
from app.matching.matcher import MatchResult, RemoteEventData, ResolvedLocalBlock, match_local_blocks_to_remote_events
from app.matching.models import RemoteEvent
from app.matching.resolution import resolve_project_identities
from app.tracker_sync.models import LocalSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def _context_string(detail: dict, key: str) -> str | None:
    value = detail.get(key)
    return value if isinstance(value, str) and value else None


def _resolve_user_timezone(user: User) -> ZoneInfo:
    """Return the user's IANA timezone, which decides which local day each block belongs to.

    Rejects an unset or unrecognised value rather than falling back to UTC, because a silent UTC fallback is the
    misattribution this resolution exists to prevent.
    """
    if not user.timezone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No timezone is set for this account, so day boundaries cannot be determined. "
                "Set an IANA timezone name (for example 'Asia/Karachi') before reconciling."
            ),
        )
    try:
        return resolve_timezone(user.timezone)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The timezone set for this account ({user.timezone!r}) is not a recognised IANA timezone name. "
                "Set a valid name (for example 'Asia/Karachi') before reconciling."
            ),
        )


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

    def as_utc_bounds(self, tz: tzinfo) -> tuple[datetime, datetime]:
        """Return the half-open UTC span `[start, end)` covering this local-day range in `tz`."""
        return (
            datetime.combine(self.date_range_start, time.min, tzinfo=tz).astimezone(timezone.utc),
            datetime.combine(self.date_range_end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc),
        )


class ReconciliationApproveRequest(ReconciliationDateRange):
    """Contain a human-approved draft and the range required to re-derive its evidence."""

    draft_id: int = Field(gt=0)
    draft: ReviewWorkLogDraft


class ReconciliationGenerateRequest(ReconciliationDateRange):
    """Identify the selected scope and, for regeneration, the active draft expected to be replaced."""

    replace_draft_id: int | None = Field(default=None, gt=0)


class PersistedReconciliationResult(BaseModel):
    """Return a persisted reconciliation generation and its lifecycle identity."""

    draft_id: int
    state: ReconciliationDraftState
    date_range_start: date
    date_range_end: date
    generated_at: datetime
    draft: ReviewWorkLogDraft
    verification: VerificationResult


class DiscardedReconciliationResult(BaseModel):
    """Return the identity of a reconciliation draft the user abandoned before approval."""

    draft_id: int
    state: ReconciliationDraftState


def _gather_evidence(
    db: Session, user_id: int, start_dt: datetime, end_dt: datetime, tz: tzinfo
) -> MatchResult:
    """Classify and aggregate sessions, exclude Idle blocks, split them on `tz` midnights, and match remote events.

    `start_dt`/`end_dt` bound a half-open UTC span.
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
                RemoteEvent.occurred_at < end_dt,
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
        )
        .order_by(LocalSession.started_at.asc(), LocalSession.ended_at.asc(), LocalSession.id.asc())
        .all()
    )

    raw_rows = []
    for session in sessions:
        context_detail = parse_context_detail(session.context_detail)
        classification = classify_session(
            bundle_id=session.bundle_id,
            window_title=session.window_title,
            project_path=session.project_path,
            context_detail=context_detail,
        )
        raw_rows.append(
            RawSessionRow(
                project=session.project_path,
                app=session.app_name,
                start_time=session.started_at,
                end_time=session.ended_at,
                category=classification.category,
                session_id=session.id,
                window_title=session.window_title,
                meeting_name=classification.meeting_name,
                branch=_context_string(context_detail, "git_branch")
                or _context_string(context_detail, "branch"),
                project_name=_context_string(context_detail, "project_name"),
                active_file=_context_string(context_detail, "active_file"),
                tool=_context_string(context_detail, "tool"),
                url=_context_string(context_detail, "url"),
                cwd=_context_string(context_detail, "cwd"),
                browser=_context_string(context_detail, "browser"),
                end_reason=session.end_reason,
                bundle_id=session.bundle_id,
            )
        )

    blocks = split_blocks_at_local_midnight(
        [block for block in aggregate_local_activity(raw_rows, tz) if block.category != SessionCategory.idle],
        tz,
    )

    identity_cache: dict[str, dict[str, str | None]] = {}
    resolved = []
    for block in blocks:
        if block.project is None:
            resolved.append(ResolvedLocalBlock(block=block, remote_identities={}))
            continue
        if block.project not in identity_cache:
            identity_cache[block.project] = resolve_project_identities(db, user_id, block.project)
        resolved.append(ResolvedLocalBlock(block=block, remote_identities=identity_cache[block.project]))

    return match_local_blocks_to_remote_events(resolved, remote_events)


@router.post("/generate", response_model=PersistedReconciliationResult)
async def generate_reconciliation(
    payload: ReconciliationGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersistedReconciliationResult:
    """Generate, verify, and persist a reconciliation draft with immutable AI entry snapshots."""
    tz = _resolve_user_timezone(current_user)
    _resolve_replaced_draft(db, current_user.id, payload)
    start_dt, end_dt = payload.as_utc_bounds(tz)
    match_result = await run_in_threadpool(_gather_evidence, db, current_user.id, start_dt, end_dt, tz)

    result = await reconcile_evidence(
        matched_groups=match_result.matched,
        unmatched_blocks=match_result.unmatched_blocks,
        unmatched_events=match_result.unmatched_events,
        llm_provider=get_llm_provider(),
        tz=tz,
    )
    db.query(User).filter(User.id == current_user.id).with_for_update().one()
    replaced = _resolve_replaced_draft(db, current_user.id, payload)
    if replaced is not None:
        replaced.state = ReconciliationDraftState.superseded
        for entry in replaced.entries:
            if entry.status == EntryStatus.draft:
                entry.status = EntryStatus.discarded

    persisted = ReconciliationDraft(
        user_id=current_user.id,
        date_range_start=payload.date_range_start,
        date_range_end=payload.date_range_end,
        state=ReconciliationDraftState.active,
        draft=result.draft.model_dump(mode="json"),
        verification=result.verification.model_dump(mode="json"),
        supersedes_id=replaced.id if replaced is not None else None,
    )
    db.add(persisted)
    db.flush()

    review_draft_data = result.draft.model_dump(mode="json")
    generated_evidence = build_evidence(
        match_result.matched, match_result.unmatched_blocks, match_result.unmatched_events
    )
    for draft_entry in review_draft_data["entries"]:
        for allocation in draft_entry["allocations"]:
            block = generated_evidence.blocks_by_id[allocation["block_id"]]
            allocation["date"] = local_date(block.start_time, tz).isoformat()
    for residual in review_draft_data["residual_unassigned_minutes"]:
        block = generated_evidence.blocks_by_id[residual["block_id"]]
        residual["date"] = local_date(block.start_time, tz).isoformat()
    for position, draft_entry in enumerate(result.draft.entries):
        entry = Entry(
            user_id=current_user.id,
            format=EntryFormat.project_log,
            content=_entry_content(draft_entry),
            work_date=draft_entry.date,
            status=EntryStatus.draft,
            reconciliation_draft_id=persisted.id,
            draft_position=position,
        )
        db.add(entry)
        db.flush()
        review_draft_data["entries"][position]["entry_id"] = entry.id
        review_draft_data["entries"][position]["origin"] = "evidence"
        db.add(EntryVersion(entry_id=entry.id, source=EntryVersionSource.ai_draft, content=entry.content))

    persisted.draft = ReviewWorkLogDraft.model_validate(review_draft_data).model_dump(mode="json")
    db.commit()
    db.refresh(persisted)
    return _persisted_result(persisted)


def _resolve_replaced_draft(
    db: Session, user_id: int, payload: ReconciliationGenerateRequest
) -> ReconciliationDraft | None:
    """Enforce one non-superseded reconciliation scope per covered day and validate regeneration identity."""
    conflicts = (
        db.query(ReconciliationDraft)
        .filter(
            ReconciliationDraft.user_id == user_id,
            ReconciliationDraft.state.in_(
                [ReconciliationDraftState.active, ReconciliationDraftState.approved]
            ),
            ReconciliationDraft.date_range_start <= payload.date_range_end,
            ReconciliationDraft.date_range_end >= payload.date_range_start,
        )
        .order_by(ReconciliationDraft.id.asc())
        .all()
    )
    exact_active = next(
        (
            draft
            for draft in conflicts
            if draft.state == ReconciliationDraftState.active
            and draft.date_range_start == payload.date_range_start
            and draft.date_range_end == payload.date_range_end
        ),
        None,
    )
    if exact_active is not None and payload.replace_draft_id == exact_active.id and len(conflicts) == 1:
        return exact_active
    if exact_active is not None and payload.replace_draft_id != exact_active.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active draft already exists for this scope. Reload it before regenerating.",
        )
    if conflicts:
        conflict = conflicts[0]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The selected scope overlaps an existing active or approved reconciliation "
                f"({conflict.date_range_start} to {conflict.date_range_end})."
            ),
        )
    if payload.replace_draft_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The draft selected for regeneration is no longer active. Reload the selected dates.",
        )
    return None


def _persisted_result(persisted: ReconciliationDraft) -> PersistedReconciliationResult:
    return PersistedReconciliationResult(
        draft_id=persisted.id,
        state=persisted.state,
        date_range_start=persisted.date_range_start,
        date_range_end=persisted.date_range_end,
        generated_at=persisted.generated_at,
        draft=ReviewWorkLogDraft.model_validate(persisted.draft),
        verification=VerificationResult.model_validate(persisted.verification),
    )


@router.get("/drafts/current", response_model=PersistedReconciliationResult)
def get_current_reconciliation_draft(
    payload: ReconciliationDateRange = Depends(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersistedReconciliationResult:
    """Fetch the active or approved draft that overlaps the selected scope."""
    persisted = (
        db.query(ReconciliationDraft)
        .filter(
            ReconciliationDraft.user_id == current_user.id,
            ReconciliationDraft.date_range_start <= payload.date_range_end,
            ReconciliationDraft.date_range_end >= payload.date_range_start,
            ReconciliationDraft.state.notin_(
                [ReconciliationDraftState.superseded, ReconciliationDraftState.discarded]
            ),
        )
        .order_by(ReconciliationDraft.generated_at.desc(), ReconciliationDraft.id.desc())
        .first()
    )
    if persisted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation draft not found")
    return _persisted_result(persisted)


@router.post("/drafts/{draft_id}/discard", response_model=DiscardedReconciliationResult)
def discard_reconciliation_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscardedReconciliationResult:
    """Abandon an active reconciliation draft before approval, freeing its scope for a fresh generate.

    Only drafts that were never approved can be discarded. Approved reconciliation is final by design; its
    entries are corrected through the existing post-approval revision path instead. The user-row lock serializes
    this lifecycle mutation with generate and approve, per the ADR's single-lock rule. Discarded drafts keep their
    immutable ``ai_draft`` entry-version history; they are never deleted.
    """
    db.query(User).filter(User.id == current_user.id).with_for_update().one()
    persisted = (
        db.query(ReconciliationDraft)
        .filter(ReconciliationDraft.id == draft_id, ReconciliationDraft.user_id == current_user.id)
        .with_for_update()
        .first()
    )
    if persisted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation draft not found")
    if persisted.state != ReconciliationDraftState.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This reconciliation draft is {persisted.state.value} and cannot be discarded. "
                "Only an active draft can be abandoned before approval."
            ),
        )
    persisted.state = ReconciliationDraftState.discarded
    for entry in persisted.entries:
        if entry.status == EntryStatus.draft:
            entry.status = EntryStatus.discarded
    db.commit()
    db.refresh(persisted)
    return DiscardedReconciliationResult(draft_id=persisted.id, state=persisted.state)


def _entry_content(draft_entry) -> dict:
    """Build persisted approved-entry content with its allocations, tag, and citations."""
    origin = getattr(draft_entry, "origin", "evidence")
    return normalize_entry_content(
        EntryFormat.project_log,
        {
            "text": draft_entry.description,
            "project": draft_entry.project,
            "tag": draft_entry.tag.value,
            "allocations": (
                [{"block_id": a.block_id, "minutes": a.minutes} for a in draft_entry.allocations]
                if draft_entry.allocations
                else None
            ),
            "source_remote_event_ids": draft_entry.source_remote_event_ids,
            "review_reason": draft_entry.review_reason,
            "origin": origin,
            "manual_minutes": getattr(draft_entry, "manual_minutes", None),
        },
    )


@router.post("/approve", response_model=list[EntryResponse], status_code=status.HTTP_201_CREATED)
async def approve_reconciliation(
    payload: ReconciliationApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Entry]:
    """Re-verify and atomically approve the persisted draft entries and any submitted manual entries.

    Reminders and residual allocations are deliberately not persisted because they are not work-log entries.
    """
    tz = _resolve_user_timezone(current_user)
    db.query(User).filter(User.id == current_user.id).with_for_update().one()
    persisted = (
        db.query(ReconciliationDraft)
        .filter(ReconciliationDraft.id == payload.draft_id, ReconciliationDraft.user_id == current_user.id)
        .with_for_update()
        .first()
    )
    if persisted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation draft not found")
    if persisted.state != ReconciliationDraftState.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This reconciliation draft is no longer active. Reload the selected dates.",
        )
    if (
        persisted.date_range_start != payload.date_range_start
        or persisted.date_range_end != payload.date_range_end
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected dates no longer match this reconciliation draft. Reload before saving.",
        )
    if any(
        entry.date < persisted.date_range_start or entry.date > persisted.date_range_end
        for entry in payload.draft.entries
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Every draft entry date must be inside the persisted reconciliation scope.",
        )

    start_dt, end_dt = payload.as_utc_bounds(tz)
    match_result = await run_in_threadpool(_gather_evidence, db, current_user.id, start_dt, end_dt, tz)

    evidence = build_evidence(
        matched_groups=match_result.matched,
        unmatched_blocks=match_result.unmatched_blocks,
        unmatched_events=match_result.unmatched_events,
    )

    reviewed_draft = payload.draft.model_copy(deep=True)
    reviewed_draft.tracked_wall_clock_minutes = compute_tracked_wall_clock_minutes(evidence.blocks_by_id.values())
    for draft_entry in reviewed_draft.entries:
        for allocation in draft_entry.allocations:
            block = evidence.blocks_by_id.get(allocation.block_id)
            if block is not None:
                allocation.date = local_date(block.start_time, tz)
    for residual in reviewed_draft.residual_unassigned_minutes:
        block = evidence.blocks_by_id.get(residual.block_id)
        if block is not None:
            residual.date = local_date(block.start_time, tz)

    verification = verify_draft(reviewed_draft, evidence, tz)
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

    persisted_entries = {
        entry.id: entry for entry in persisted.entries if entry.status == EntryStatus.draft
    }
    submitted_evidence = [entry for entry in payload.draft.entries if entry.origin == "evidence"]
    submitted_ids = [entry.entry_id for entry in submitted_evidence]
    if (
        any(entry_id is None for entry_id in submitted_ids)
        or len(set(submitted_ids)) != len(submitted_ids)
        or any(entry_id not in persisted_entries for entry_id in submitted_ids)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Submitted evidence entries do not match the persisted reconciliation draft.",
        )

    approved_at = datetime.now(timezone.utc)
    entries: list[Entry] = []
    approved_draft = reviewed_draft
    for position, draft_entry in enumerate(approved_draft.entries):
        if draft_entry.origin == "evidence":
            entry_id = draft_entry.entry_id
            assert entry_id is not None
            entry = persisted_entries[entry_id]
            entry.content = _entry_content(draft_entry)
            entry.work_date = draft_entry.date
            entry.status = EntryStatus.approved
            entry.approved_at = approved_at
            entry.draft_position = position
        else:
            if draft_entry.entry_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="A new manual entry cannot claim an existing entry ID.",
                )
            entry = Entry(
                user_id=current_user.id,
                format=EntryFormat.project_log,
                content=_entry_content(draft_entry),
                work_date=draft_entry.date,
                status=EntryStatus.approved,
                approved_at=approved_at,
                reconciliation_draft_id=persisted.id,
                draft_position=position,
            )
            db.add(entry)
            db.flush()
            draft_entry.entry_id = entry.id
        db.add(EntryVersion(entry_id=entry.id, source=EntryVersionSource.human_approved, content=entry.content))
        entries.append(entry)

    approved_ids = {entry.id for entry in entries}
    for entry in persisted_entries.values():
        if entry.id not in approved_ids:
            entry.status = EntryStatus.discarded

    persisted.state = ReconciliationDraftState.approved
    persisted.approved_at = approved_at
    persisted.draft = approved_draft.model_dump(mode="json")
    persisted.verification = verification.model_dump(mode="json")

    db.commit()
    for entry in entries:
        db.refresh(entry)

    return entries
