"""Stage 6: code-side verification of a reconciliation draft against its evidence.

Schema-valid does not mean correct — the schema ignores evidence, so it cannot verify that charged
minutes match measured minutes, that cited ids existed, or that no block was silently dropped.
`verify_draft` closes that gap, running before the draft reaches a human. It reports only; it does
not repair (auto-correction would silently manufacture answers the evidence does not support).

Checks are independent and complete on their own, so one defect can surface as multiple issues —
intentionally. A block overcharged across entries is reported by both `conservation` and
`cross_entry_duplicate` because each check answers a different question and suppressing one
would make a check silently incomplete for readers filtering on it.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.agent.reconciliation.evidence import EvidenceBundle, block_minutes, compute_overlaps
from app.agent.reconciliation.schemas import WorkLogDraft
from app.local_activity.classification import SessionCategory

CHECK_CONSERVATION = "conservation"
CHECK_UNKNOWN_ID = "unknown_id"
CHECK_COMPLETENESS = "completeness"
CHECK_CROSS_ENTRY_DUPLICATE = "cross_entry_duplicate"
CHECK_DUPLICATE_REMINDER = "duplicate_reminder"
CHECK_UNEXPLAINED_OVERLAP = "unexplained_overlap"

RESIDUAL_FIELD = "residual_unassigned_minutes"


@dataclass(frozen=True)
class _Charge:
    """One `BlockAllocation` found in the draft, tagged with where it came from.

    `entry_index` is the position in `draft.entries`, or None for allocations from
    `residual_unassigned_minutes`. Flattening into one list lets conservation sum a block across the
    whole draft, which is the only level at which "all measured time is accounted for" is meaningful.
    """

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
    """The outcome of verifying one draft. `passed` is False as soon as any error-severity issue exists."""

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
    """Every block's charged minutes must equal its measured minutes exactly.

    Under-allocation means measured time was lost; over-allocation means time was invented. Neither
    is recoverable from the draft alone, so both are errors. No minimum-duration allowance is applied
    here — the prompt's sub-30-minute exemption applies to entry floor, not block rounding.
    """
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
    """Every id named by the draft must be an id the evidence actually contained.

    A fabricated citation looks more verified than no citation, so this is checked separately. Reminder
    citations are checked with the same severity as entry citations even though we cannot tell
    pre-built reminders from model reminders — a factual error is a factual error regardless of source.
    """
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
    """Every measured block must be accounted for as work, as residual, or both — never silently dropped.

    A block appearing nowhere is an error (the day's total quietly shrinks). A block appearing in both
    an entry and residual is a warning — splitting between "can attribute" and "cannot" is legitimate,
    but worth reviewing because the model simultaneously claims to and does not know what the block was.
    """
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
    """No block may be charged past its measured total by spreading overcharge across entries.

    `DraftEntry`'s validator rejects duplication within one entry, but at draft scope two entries can
    each charge block 1 for its full duration, escaping that check. This check catches the same defect
    at draft scope, naming the entries and charges involved.
    """
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
    """Flag any remote event covered by more than one reminder.

    Stage 5 does not deduplicate pre-built and model reminders, so duplicates reach here intact.
    The pre-built generator and model both identifying the same event is a signal, not noise — it is
    a warning so the reviewer can choose which wording to keep, but the draft is not wrong.
    """
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
    """Any two blocks whose measured time windows overlap must involve a Meeting block.

    Overlapping blocks are allowed by design -- a meeting's full span and a genuinely concurrent
    workstream may legitimately both be charged at their full measured minutes (see
    `aggregation.py::_merge_unlimited_within_day` for how a Meeting block's span is produced). This is not
    an exemption from conservation: `_check_conservation` above still requires each block's own charged
    minutes to equal its own measured minutes, independently, so an overlap never lets time be double
    -counted within a single block's total. What this check guards against is a different failure: two
    *non*-Meeting blocks overlapping in time should be structurally impossible (raw tracker sessions are
    exclusive, and non-Meeting aggregation still uses the ordinary gap threshold), so if it happens anyway
    it signals a classification or aggregation bug quietly inflating the day's total tracked minutes
    beyond what real, non-double-booked time supports -- exactly the kind of silently-lost-or-invented time
    this whole verifier exists to catch.
    """
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


def verify_draft(draft: WorkLogDraft, evidence: EvidenceBundle) -> VerificationResult:
    """Check a Stage 5 draft against its evidence and report every problem.

    Verifies: block charged minutes equal measured minutes; all named block/event ids were in evidence;
    every block is accounted for; no block is overcharged across entries; no remote event has duplicate
    reminders; no two overlapping blocks exist unless a Meeting block explains the overlap.

    Returns `VerificationResult` with `passed` True only if no error-severity issue exists. Warnings
    mark things for human review but do not fail the draft. The draft is never modified; a failing
    draft is a draft for review, not automatic correction. Scope is structural/factual only — judgment
    quality (vague descriptions, missing citations) is not verified here, only that arithmetic and
    references check out against measured input.
    """
    charges = _collect_charges(draft)
    issues: list[VerificationIssue] = []

    _check_conservation(charges, evidence, issues)
    _check_unknown_ids(draft, charges, evidence, issues)
    _check_completeness(charges, evidence, issues)
    _check_cross_entry_duplicates(charges, evidence, issues)
    _check_duplicate_reminders(draft, issues)
    _check_unexplained_overlap(evidence, issues)

    passed = not any(issue.severity == "error" for issue in issues)
    return VerificationResult(passed=passed, issues=issues)
