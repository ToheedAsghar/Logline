"""Expose read-only draft generation and verified human approval for reconciliation."""

import logging
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent.llm import get_llm_provider
from app.agent.reconciliation.constants import MAX_RANGE_DAYS
from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.reconciler import ReconciliationResult, reconcile_evidence
from app.agent.reconciliation.schemas import WorkLogDraft
from app.agent.reconciliation.verifier import verify_draft
from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.entries.models import Entry, EntryFormat, EntryStatus, EntryVersion, EntryVersionSource
from app.entries.schemas import EntryResponse, normalize_entry_content
from app.local_activity.aggregation import RawSessionRow, aggregate_local_activity, split_blocks_at_local_midnight
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
        return ZoneInfo(user.timezone)
    except (ZoneInfoNotFoundError, ValueError):
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

    draft: WorkLogDraft


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


@router.post("/generate", response_model=ReconciliationResult)
async def generate_reconciliation(
    payload: ReconciliationDateRange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReconciliationResult:
    """Generate and verify a draft from stored evidence without persisting it."""
    tz = _resolve_user_timezone(current_user)
    start_dt, end_dt = payload.as_utc_bounds(tz)
    match_result = await run_in_threadpool(_gather_evidence, db, current_user.id, start_dt, end_dt, tz)

    return await reconcile_evidence(
        matched_groups=match_result.matched,
        unmatched_blocks=match_result.unmatched_blocks,
        unmatched_events=match_result.unmatched_events,
        llm_provider=get_llm_provider(),
        tz=tz,
    )


def _entry_content(draft_entry) -> dict:
    """Build persisted approved-entry content with its allocations, tag, and citations."""
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
    """Re-verify and atomically persist a human-approved draft as approved entries.

    Reminders and residual allocations are deliberately not persisted because they are not work-log entries.
    """
    tz = _resolve_user_timezone(current_user)
    start_dt, end_dt = payload.as_utc_bounds(tz)
    match_result = await run_in_threadpool(_gather_evidence, db, current_user.id, start_dt, end_dt, tz)

    evidence = build_evidence(
        matched_groups=match_result.matched,
        unmatched_blocks=match_result.unmatched_blocks,
        unmatched_events=match_result.unmatched_events,
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
