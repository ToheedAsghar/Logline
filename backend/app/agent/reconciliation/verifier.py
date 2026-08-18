"""Verify a reconciliation draft's allocations and citations against its evidence without modifying it."""

from dataclasses import dataclass
from datetime import timezone, tzinfo
from typing import Literal

from pydantic import BaseModel

from app.agent.reconciliation.constants import (
    CHECK_ALLOCATION_DATE, CHECK_COMPLETENESS, CHECK_CONSERVATION, CHECK_CROSS_ENTRY_DUPLICATE,
    CHECK_DESCRIPTION_DURATION_LANGUAGE, CHECK_DUPLICATE_REMINDER, CHECK_UNEXPLAINED_OVERLAP, CHECK_UNKNOWN_ID,
    RESIDUAL_FIELD,
)
from app.agent.reconciliation.evidence import EvidenceBundle, block_minutes, compute_overlaps
from app.agent.reconciliation.schemas import WorkLogDraft, find_duration_language
from app.local_activity.aggregation import local_date
from app.local_activity.classification import SessionCategory


@dataclass(frozen=True)
class _Charge:
    """Represent a draft allocation and its entry index, or None for a residual allocation."""

    block_id: int
    minutes: int
    entry_index: int | None


class VerificationIssue(BaseModel):
    """One specific problem found in a draft, in terms a human reviewer can act on."""

    severity: Literal["error", "warning"]
    check: str
    detail: str
    block_id: int | None = None
    entry_index: int | None = None


class VerificationResult(BaseModel):
    """Contain verification issues and whether any error-severity issue was found."""

    passed: bool
    issues: list[VerificationIssue]


def _where(entry_index: int | None) -> str:
    return RESIDUAL_FIELD if entry_index is None else f"entry {entry_index}"


def _collect_charges(draft: WorkLogDraft) -> list[_Charge]:
    """Flatten every allocation in the draft, entries first in order, then residual."""
    charges = [
        _Charge(block_id=allocation.block_id, minutes=allocation.minutes, entry_index=index)
        for index, entry in enumerate(draft.entries)
        for allocation in entry.allocations
    ]
    charges.extend(
        _Charge(block_id=allocation.block_id, minutes=allocation.minutes, entry_index=None)
        for allocation in draft.residual_unassigned_minutes
    )
    return charges


def _check_conservation(
    charges: list[_Charge], evidence: EvidenceBundle, issues: list[VerificationIssue]
) -> None:
    """Report blocks whose total charged minutes differ from their measured minutes."""
    charged_by_block: dict[int, int] = {}
    for charge in charges:
        charged_by_block[charge.block_id] = charged_by_block.get(charge.block_id, 0) + charge.minutes

    for block_id in sorted(evidence.blocks_by_id):
        measured = block_minutes(evidence.blocks_by_id[block_id])
        charged = charged_by_block.get(block_id, 0)
        if charged == measured:
            continue

        direction = "over-allocated" if charged > measured else "under-allocated"
        lost_or_invented = "time was invented" if charged > measured else "measured time was silently lost"
        issues.append(
            VerificationIssue(
                severity="error",
                check=CHECK_CONSERVATION,
                detail=(
                    f"block {block_id} is {direction}: {charged} min charged across the draft against "
                    f"{measured} min measured ({abs(charged - measured)} min discrepancy -- {lost_or_invented})"
                ),
                block_id=block_id,
            )
        )


def _check_unknown_ids(
    draft: WorkLogDraft, charges: list[_Charge], evidence: EvidenceBundle, issues: list[VerificationIssue]
) -> None:
    """Report allocation and event IDs that are absent from the evidence bundle."""
    for charge in charges:
        if charge.block_id in evidence.blocks_by_id:
            continue
        issues.append(
            VerificationIssue(
                severity="error",
                check=CHECK_UNKNOWN_ID,
                detail=(
                    f"{_where(charge.entry_index)} charges {charge.minutes} min to block {charge.block_id}, "
                    f"which was never in the evidence (known block ids: "
                    f"{sorted(evidence.blocks_by_id) or 'none'})"
                ),
                block_id=charge.block_id,
                entry_index=charge.entry_index,
            )
        )

    for index, entry in enumerate(draft.entries):
        for event_id in entry.source_remote_event_ids:
            if event_id in evidence.remote_event_ids:
                continue
            issues.append(
                VerificationIssue(
                    severity="error",
                    check=CHECK_UNKNOWN_ID,
                    detail=(
                        f"entry {index} cites remote event {event_id!r}, which was never in the evidence -- "
                        f"this is a fabricated citation"
                    ),
                    entry_index=index,
                )
            )

    for index, reminder in enumerate(draft.reminders):
        for event_id in reminder.source_remote_event_ids:
            if event_id in evidence.remote_event_ids:
                continue
            issues.append(
                VerificationIssue(
                    severity="error",
                    check=CHECK_UNKNOWN_ID,
                    detail=(
                        f"reminder {index} cites remote event {event_id!r}, which was never in the evidence -- "
                        f"this is a fabricated citation"
                    ),
                )
            )


def _check_completeness(
    charges: list[_Charge], evidence: EvidenceBundle, issues: list[VerificationIssue]
) -> None:
    """Report measured blocks omitted from both entries and residual allocations."""
    entries_by_block: dict[int, list[int]] = {}
    residual_blocks: set[int] = set()
    for charge in charges:
        if charge.entry_index is None:
            residual_blocks.add(charge.block_id)
        else:
            entries_by_block.setdefault(charge.block_id, []).append(charge.entry_index)

    for block_id in sorted(evidence.blocks_by_id):
        measured = block_minutes(evidence.blocks_by_id[block_id])
        in_entries = entries_by_block.get(block_id, [])
        in_residual = block_id in residual_blocks

        if not in_entries and not in_residual:
            issues.append(
                VerificationIssue(
                    severity="error",
                    check=CHECK_COMPLETENESS,
                    detail=(
                        f"block {block_id} ({measured} min measured) appears in no entry and not in "
                        f"{RESIDUAL_FIELD}; its measured time was silently dropped from the draft"
                    ),
                    block_id=block_id,
                )
            )
        elif in_entries and in_residual:
            entry_list = ", ".join(str(index) for index in sorted(set(in_entries)))
            issues.append(
                VerificationIssue(
                    severity="warning",
                    check=CHECK_COMPLETENESS,
                    detail=(
                        f"block {block_id} is split between entries ({entry_list}) and {RESIDUAL_FIELD}; the "
                        f"draft both attributes and declines to attribute part of the same block"
                    ),
                    block_id=block_id,
                )
            )


def _check_cross_entry_duplicates(
    charges: list[_Charge], evidence: EvidenceBundle, issues: list[VerificationIssue]
) -> None:
    """Report blocks charged past their measured total across multiple entries."""
    minutes_by_entry: dict[int, dict[int, int]] = {}
    for charge in charges:
        if charge.entry_index is None:
            continue
        per_entry = minutes_by_entry.setdefault(charge.block_id, {})
        per_entry[charge.entry_index] = per_entry.get(charge.entry_index, 0) + charge.minutes

    for block_id in sorted(evidence.blocks_by_id):
        per_entry = minutes_by_entry.get(block_id, {})
        if len(per_entry) < 2:
            continue

        measured = block_minutes(evidence.blocks_by_id[block_id])
        total = sum(per_entry.values())
        if total <= measured:
            continue

        breakdown = ", ".join(f"entry {index} charges {per_entry[index]} min" for index in sorted(per_entry))
        issues.append(
            VerificationIssue(
                severity="error",
                check=CHECK_CROSS_ENTRY_DUPLICATE,
                detail=(
                    f"block {block_id} is charged across {len(per_entry)} entries totalling {total} min "
                    f"against {measured} min measured ({breakdown}); the same measured time is counted more "
                    f"than once"
                ),
                block_id=block_id,
            )
        )


def _check_duplicate_reminders(draft: WorkLogDraft, issues: list[VerificationIssue]) -> None:
    """Warn when more than one reminder cites the same remote event."""
    reminders_by_event: dict[str, list[int]] = {}
    for index, reminder in enumerate(draft.reminders):
        for event_id in dict.fromkeys(reminder.source_remote_event_ids):
            reminders_by_event.setdefault(event_id, []).append(index)

    for event_id, indices in reminders_by_event.items():
        if len(indices) < 2:
            continue
        listed = ", ".join(str(index) for index in indices)
        issues.append(
            VerificationIssue(
                severity="warning",
                check=CHECK_DUPLICATE_REMINDER,
                detail=(
                    f"remote event {event_id!r} is covered by {len(indices)} reminders (indices {listed}); "
                    f"a pre-built reminder and a model reminder may be asking the same question"
                ),
            )
        )


def _check_unexplained_overlap(evidence: EvidenceBundle, issues: list[VerificationIssue]) -> None:
    """Report overlapping blocks unless either block is a Meeting."""
    overlaps = compute_overlaps(evidence.blocks_by_id)
    reported: set[frozenset[int]] = set()

    for block_id, overlapping_ids in overlaps.items():
        block = evidence.blocks_by_id[block_id]
        for other_id in overlapping_ids:
            pair = frozenset({block_id, other_id})
            if pair in reported:
                continue

            other = evidence.blocks_by_id[other_id]
            if block.category == SessionCategory.meeting or other.category == SessionCategory.meeting:
                continue

            reported.add(pair)
            issues.append(
                VerificationIssue(
                    severity="error",
                    check=CHECK_UNEXPLAINED_OVERLAP,
                    detail=(
                        f"block {block_id} ({block.category.value}) and block {other_id} "
                        f"({other.category.value}) have overlapping measured time windows, but neither is a "
                        f"Meeting block -- overlap is only legitimate when a meeting's span covers "
                        f"concurrent work"
                    ),
                    block_id=block_id,
                )
            )


def _check_description_duration_language(draft: WorkLogDraft, issues: list[VerificationIssue]) -> None:
    """Report entry descriptions containing duration language."""
    for index, entry in enumerate(draft.entries):
        label = find_duration_language(entry.description)
        if label is not None:
            issues.append(
                VerificationIssue(
                    severity="error",
                    check=CHECK_DESCRIPTION_DURATION_LANGUAGE,
                    detail=(
                        f"entry {index}'s description contains duration/time language (matched: {label}): "
                        f"{entry.description!r}"
                    ),
                    entry_index=index,
                )
            )


def _check_allocation_dates(
    draft: WorkLogDraft, evidence: EvidenceBundle, issues: list[VerificationIssue], tz: tzinfo
) -> None:
    """Reject measured allocations placed on a different local day from their source block."""
    for index, entry in enumerate(draft.entries):
        for allocation in entry.allocations:
            block = evidence.blocks_by_id.get(allocation.block_id)
            if block is None or local_date(block.start_time, tz) == entry.date:
                continue
            issues.append(
                VerificationIssue(
                    severity="error",
                    check=CHECK_ALLOCATION_DATE,
                    detail=(
                        f"entry {index} is dated {entry.date}, but block {allocation.block_id} belongs to "
                        f"{local_date(block.start_time, tz)} in the user's timezone"
                    ),
                    block_id=allocation.block_id,
                    entry_index=index,
                )
            )


def verify_draft(draft: WorkLogDraft, evidence: EvidenceBundle, tz: tzinfo = timezone.utc) -> VerificationResult:
    """Verify a Stage 5 draft against evidence and return all structural and factual issues."""
    charges = _collect_charges(draft)
    issues: list[VerificationIssue] = []

    _check_conservation(charges, evidence, issues)
    _check_unknown_ids(draft, charges, evidence, issues)
    _check_completeness(charges, evidence, issues)
    _check_cross_entry_duplicates(charges, evidence, issues)
    _check_duplicate_reminders(draft, issues)
    _check_unexplained_overlap(evidence, issues)
    _check_description_duration_language(draft, issues)
    _check_allocation_dates(draft, evidence, issues, tz)

    passed = not any(issue.severity == "error" for issue in issues)
    return VerificationResult(passed=passed, issues=issues)
