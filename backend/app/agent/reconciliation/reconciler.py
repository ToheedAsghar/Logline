"""Stage 5: the AI reconciliation call, with Stage 6 verification attached.

Assembles evidence, makes one structured-output call, merges pre-built reminders into the draft, and
verifies the result. The draft and its verification are always returned together in a
`ReconciliationResult`, even if verification fails — a human needs to see what the model said to fix it.

Pre-built reminders never reach the model; they are appended in code so the model cannot reword or
claim credit for them. No retry or auto-correction logic — that is a policy decision left to the
caller, not settled here by accident.

Reminders are derived here from `unmatched_events`, not accepted as a separate parameter -- a reminder
citing an event id the evidence never saw would look like a fabricated citation to Stage 6. Deriving
both from the same list structurally rules that out; it cannot happen by a caller passing mismatched
values from two different matcher runs.
"""

from datetime import timezone, tzinfo
from typing import get_args

from pydantic import BaseModel

from app.agent.llm.base import LLMProvider, Message
from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.prompt import SYSTEM_PROMPT
from app.agent.reconciliation.schemas import (
    REMINDER_NOTE_MAX_LENGTH, DraftReminder, ReminderSource, WorkLogDraft, find_duration_language,
)
from app.agent.reconciliation.verifier import VerificationResult, verify_draft
from app.local_activity.aggregation import LocalActivityBlock
from app.matching.matcher import MatchedGroup, RemoteEventData
from app.reminders.generator import Reminder, generate_reminders

VALID_REMINDER_SOURCES: frozenset[str] = frozenset(get_args(ReminderSource))

UNIDENTIFIED_PROJECT = "an unidentified project"
NOTE_WITH_SUMMARIES = "Unlogged {source} activity on {project}: {summaries}"
NOTE_WITHOUT_SUMMARIES = "Unlogged {source} activity on {project}, with no measured local activity."
NOTE_LAST_RESORT = "Unlogged remote activity with no measured local activity."
TRUNCATION_SUFFIX = "..."

ERROR_UNKNOWN_REMINDER_SOURCE = (
    "cannot convert a reminder from source {source!r} into a DraftReminder; DraftReminder.source accepts only "
    "{allowed}. A reminder reached Stage 5 from a source the draft schema does not model."
)


class ReconciliationResult(BaseModel):
    """One reconciliation: the model's draft and the result of code-side verification.

    Both fields are always populated. `verification.passed` being False means the draft has problems
    for human review, not that it is absent — a failing verification is information about a draft,
    not a reason to withhold it.
    """

    draft: WorkLogDraft
    verification: VerificationResult


def _truncate_note(note: str) -> str:
    if len(note) <= REMINDER_NOTE_MAX_LENGTH:
        return note
    keep = REMINDER_NOTE_MAX_LENGTH - len(TRUNCATION_SUFFIX)
    return note[:keep].rstrip() + TRUNCATION_SUFFIX


def _build_note(reminder: Reminder) -> str:
    """Build a note for a pre-built reminder that passes `DraftReminder`'s duration-language validator.

    Remote summaries may contain duration language (e.g., PR title "Cut build time by 30 minutes"),
    which would fail validation if inlined directly. Candidates are tried richest-first; the first
    passing the same check `DraftReminder` applies is used. A fixed fallback with no interpolation
    ensures project names or sources that read as duration cannot exhaust candidates.
    """

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


async def reconcile_evidence(
    matched_groups: list[MatchedGroup],
    unmatched_blocks: list[LocalActivityBlock],
    unmatched_events: list[RemoteEventData],
    llm_provider: LLMProvider,
    tz: tzinfo = timezone.utc,
) -> ReconciliationResult:
    """Reconcile one day's evidence into a verified `WorkLogDraft` via a single structured-output call.

    Pre-built reminders are derived from `unmatched_events` here, not accepted from the caller -- see
    the module docstring for why.

    Raises `LLMStructuredOutputError` if the provider cannot produce a valid draft, and `ValueError` if
    evidence contains naive datetimes or a reminder from an unknown source.
    """

    bundle = build_evidence(matched_groups, unmatched_blocks, unmatched_events, tz=tz)
    messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=bundle.user_content),
    ]

    draft = await llm_provider.run_structured(messages, WorkLogDraft)

    reminders = generate_reminders(unmatched_events, tz=tz)
    merged_reminders = [prebuilt_reminder_to_draft_reminder(reminder) for reminder in reminders]
    merged_reminders.extend(draft.reminders)

    merged_draft = WorkLogDraft(
        entries=draft.entries,
        reminders=merged_reminders,
        residual_unassigned_minutes=draft.residual_unassigned_minutes,
    )

    return ReconciliationResult(draft=merged_draft, verification=verify_draft(merged_draft, bundle))
