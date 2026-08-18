"""Form deterministic entries, generate per-entry descriptions, and verify the resulting reconciliation draft."""

import asyncio
from dataclasses import replace
from datetime import timezone, tzinfo
from typing import get_args

from pydantic import BaseModel

from app.agent.llm.base import LLMProvider
from app.agent.reconciliation.constants import DESCRIPTION_TRUNCATION_SUFFIX as TRUNCATION_SUFFIX
from app.agent.reconciliation.constants import (
    ERROR_UNKNOWN_REMINDER_SOURCE, MAX_CONCURRENT_DESCRIPTION_REQUESTS, MEETING_MULTIPLE_EVENTS_REVIEW_REASON,
    MEETING_NO_EVENT_DESCRIPTION, MEETING_UNSAFE_DESCRIPTION, NOTE_LAST_RESORT, NOTE_WITH_SUMMARIES,
    NOTE_WITHOUT_SUMMARIES, REMINDER_NOTE_MAX_LENGTH, UNIDENTIFIED_PROJECT,
)
from app.agent.reconciliation.description import describe_entry
from app.agent.reconciliation.entries import FormedEntry, fold_small_entries, form_entries, merge_adjacent_entries
from app.agent.reconciliation.evidence import EvidenceBundle, build_evidence, compute_tracked_wall_clock_minutes
from app.agent.reconciliation.schemas import (
    DraftEntry, DraftReminder, ReminderSource, WorkLogDraft, find_duration_language, truncate_description,
)
from app.agent.reconciliation.verifier import VerificationResult, verify_draft
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory
from app.local_activity.topic_refinement import refine_blocks_by_id
from app.matching.matcher import MatchedGroup, RemoteEventData
from app.reminders.generator import Reminder, generate_reminders

VALID_REMINDER_SOURCES: frozenset[str] = frozenset(get_args(ReminderSource))


class ReconciliationResult(BaseModel):
    """Contain a reconciliation draft and its code-side verification result."""

    draft: WorkLogDraft
    verification: VerificationResult


def _truncate_note(note: str) -> str:
    if len(note) <= REMINDER_NOTE_MAX_LENGTH:
        return note
    keep = REMINDER_NOTE_MAX_LENGTH - len(TRUNCATION_SUFFIX)
    return note[:keep].rstrip() + TRUNCATION_SUFFIX


def _build_note(reminder: Reminder) -> str:
    """Build a duration-free note for a generated reminder."""
    project = reminder.remote_project_id or UNIDENTIFIED_PROJECT
    summaries = "; ".join(event.summary for event in reminder.events if event.summary)

    candidates: list[str] = []
    if summaries:
        candidates.append(NOTE_WITH_SUMMARIES.format(source=reminder.source, project=project, summaries=summaries))
    candidates.append(NOTE_WITHOUT_SUMMARIES.format(source=reminder.source, project=project))
    candidates.append(NOTE_LAST_RESORT)

    for candidate in candidates:
        truncated = _truncate_note(candidate)
        if find_duration_language(truncated) is None:
            return truncated
    return NOTE_LAST_RESORT


def prebuilt_reminder_to_draft_reminder(reminder: Reminder) -> DraftReminder:
    """Convert one pre-built `Reminder` into the `DraftReminder` shape the draft carries."""
    if reminder.source not in VALID_REMINDER_SOURCES:
        raise ValueError(
            ERROR_UNKNOWN_REMINDER_SOURCE.format(
                source=reminder.source, allowed=", ".join(sorted(VALID_REMINDER_SOURCES))
            )
        )

    return DraftReminder(
        note=_build_note(reminder),
        source=reminder.source,
        day=reminder.day,
        source_remote_event_ids=[event.external_id for event in reminder.events],
    )


def _safe_meeting_description(description: str, empty_fallback: str) -> str:
    """Return a bounded, duration-free meeting description from uncontrolled calendar or tracker text."""
    candidate = truncate_description(description.strip())
    if not candidate:
        return empty_fallback
    if find_duration_language(candidate) is not None:
        return MEETING_UNSAFE_DESCRIPTION
    return candidate


def _local_meeting_description(entry: FormedEntry, bundle: EvidenceBundle) -> str:
    """Return a safe tracked meeting name or the unidentified-meeting fallback."""
    meeting_name = bundle.blocks_by_id[entry.block_ids[0]].meeting_name or ""
    return _safe_meeting_description(meeting_name, MEETING_NO_EVENT_DESCRIPTION)


def _meeting_entry_description(entry: FormedEntry, bundle: EvidenceBundle) -> tuple[str, str | None]:
    """Return a safe meeting description and an ambiguity review reason when needed."""
    events = bundle.block_events.get(entry.block_ids[0], [])
    if not events:
        return _local_meeting_description(entry, bundle), None
    earliest = min(events, key=lambda event: event.occurred_at)
    review_reason = MEETING_MULTIPLE_EVENTS_REVIEW_REASON if len(events) > 1 else None
    if earliest.summary and earliest.summary.strip():
        return _safe_meeting_description(earliest.summary, MEETING_UNSAFE_DESCRIPTION), review_reason
    return _local_meeting_description(entry, bundle), review_reason


async def _resolve_entry(
    entry: FormedEntry, bundle: EvidenceBundle, llm_provider: LLMProvider, tz: tzinfo
) -> DraftEntry:
    """Resolve one formed entry into a draft entry with its description and optional tag override."""
    if entry.category == SessionCategory.meeting:
        description, review_reason = _meeting_entry_description(entry, bundle)
        tag = entry.base_tag
    else:
        description, tag_override = await describe_entry(entry, bundle, llm_provider, tz)
        review_reason = entry.review_reason
        tag = tag_override or entry.base_tag

    return DraftEntry(
        date=entry.date,
        project=entry.project,
        allocations=entry.allocations,
        tag=tag,
        description=description,
        source_remote_event_ids=entry.source_remote_event_ids,
        review_reason=review_reason,
    )


async def reconcile_evidence(
    matched_groups: list[MatchedGroup],
    unmatched_blocks: list[LocalActivityBlock],
    unmatched_events: list[RemoteEventData],
    llm_provider: LLMProvider,
    tz: tzinfo = timezone.utc,
) -> ReconciliationResult:
    """Reconcile evidence into a verified draft with deterministic entries and generated reminders.

    Raises `ValueError` for naive evidence datetimes or unsupported reminder sources.
    """
    bundle = build_evidence(matched_groups, unmatched_blocks, unmatched_events)
    bundle = replace(bundle, blocks_by_id=refine_blocks_by_id(bundle.blocks_by_id))
    folding = fold_small_entries(merge_adjacent_entries(form_entries(bundle, tz), bundle), bundle)
    formed_entries = folding.entries
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DESCRIPTION_REQUESTS)

    async def resolve_with_limit(entry: FormedEntry) -> DraftEntry:
        async with semaphore:
            return await _resolve_entry(entry, bundle, llm_provider, tz)

    draft_entries = await asyncio.gather(
        *(resolve_with_limit(entry) for entry in formed_entries)
    )

    reminders = generate_reminders(bundle.unmatched_events, tz=tz)
    merged_reminders = [prebuilt_reminder_to_draft_reminder(reminder) for reminder in reminders]

    merged_draft = WorkLogDraft(
        entries=list(draft_entries),
        reminders=merged_reminders,
        residual_unassigned_minutes=folding.residual,
        tracked_wall_clock_minutes=compute_tracked_wall_clock_minutes(
            [group.block for group in matched_groups] + list(unmatched_blocks)
        ),
    )

    return ReconciliationResult(draft=merged_draft, verification=verify_draft(merged_draft, bundle, tz))
