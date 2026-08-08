"""Tests for Stage 6 draft verification (app/agent/reconciliation/verifier.py).

Everything here runs offline. The evidence is always built by the real `build_evidence`, never hand-assembled,
so the block ids and event ids the drafts are checked against are the same ones Stage 5 would really have put in
front of the model -- a verifier tested against a hand-made `EvidenceBundle` would only prove it agrees with the
test's own idea of the input.

Each of the five checks gets a deliberately broken draft proving that specific failure is caught, and the suite
is anchored at both ends: a reconstruction of Stage 5's real live-run evidence must pass with zero issues, and
the judgment-quality shortcomings that live run actually exhibited must not be reported as failures.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.schemas import BlockAllocation, DraftEntry, DraftReminder, EntryTag, WorkLogDraft
from app.agent.reconciliation.verifier import (
    CHECK_COMPLETENESS, CHECK_CONSERVATION, CHECK_CROSS_ENTRY_DUPLICATE, CHECK_DUPLICATE_REMINDER, CHECK_UNKNOWN_ID,
    verify_draft,
)
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory
from app.matching.matcher import MatchedGroup, RemoteEventData

UTC = timezone.utc
DAY = date(2026, 7, 24)


def make_block(
    project="logline", start_hour=9, start_minute=0, minutes=90, apps=("vscode",), category=SessionCategory.coding
):
    start = datetime(2026, 7, 24, start_hour, start_minute, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project,
        start_time=start,
        end_time=start + duration,
        duration=duration,
        apps=list(apps),
        category=category,
    )


def make_event(external_id="gh:pr:41", source="github", project="Toheed/logline", hour=9, summary="Add schema"):
    return RemoteEventData(
        external_id=external_id,
        source=source,
        remote_project_id=project,
        occurred_at=datetime(2026, 7, 24, hour, 47, tzinfo=UTC),
        event_type="pull_request",
        summary=summary,
    )


def make_entry(allocations, event_ids=("gh:pr:41",), description="Worked on the reconciliation schema"):
    return DraftEntry(
        date=DAY,
        project="logline",
        allocations=[BlockAllocation(block_id=block_id, minutes=minutes) for block_id, minutes in allocations],
        tag=EntryTag.coding,
        description=description,
        source_remote_event_ids=list(event_ids),
    )


def make_reminder(event_ids, note="Which project did the unlogged Jira transition belong to?", source="jira"):
    return DraftReminder(note=note, source=source, day=DAY, source_remote_event_ids=list(event_ids))


def residual(*allocations):
    return [BlockAllocation(block_id=block_id, minutes=minutes) for block_id, minutes in allocations]


def checks_of(result, check):
    return [issue for issue in result.issues if issue.check == check]


def errors_of(result):
    return [issue for issue in result.issues if issue.severity == "error"]


# A two-block day used by most of the broken-draft cases: block 1 measures 90 min, block 2 measures 60 min.
SIMPLE_EVIDENCE = build_evidence(
    [MatchedGroup(block=make_block(minutes=90), events=[make_event()])],
    [make_block(project="docs", start_hour=14, minutes=60)],
    [],
)


class TestAValidDraftPasses:
    def test_a_fully_correct_draft_reports_nothing_at_all(self):
        draft = WorkLogDraft(
            entries=[make_entry([(1, 90)]), make_entry([(2, 60)], event_ids=[])],
            reminders=[],
            residual_unassigned_minutes=[],
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert result.passed
        assert result.issues == []

    def test_a_block_left_entirely_in_residual_is_correct_not_a_failure(self):
        """Declining to attribute a block is an honest answer -- rule 5 of the prompt asks for exactly this."""
        draft = WorkLogDraft(entries=[make_entry([(1, 90)])], residual_unassigned_minutes=residual((2, 60)))

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert result.passed
        assert result.issues == []

    def test_a_block_legitimately_split_across_two_entries_is_not_a_failure(self):
        """The prompt explicitly asks for this when one block covers several activities; the parts sum exactly."""
        draft = WorkLogDraft(entries=[make_entry([(1, 50)]), make_entry([(1, 40), (2, 60)])])

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert result.passed
        assert result.issues == []


class TestConservationCheck:
    def test_under_allocating_a_block_is_an_error(self):
        draft = WorkLogDraft(entries=[make_entry([(1, 60)]), make_entry([(2, 60)], event_ids=[])])

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_CONSERVATION)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].block_id == 1
        assert "under-allocated" in issues[0].detail
        assert "60 min charged" in issues[0].detail and "90 min measured" in issues[0].detail

    def test_over_allocating_a_block_is_an_error(self):
        draft = WorkLogDraft(entries=[make_entry([(1, 120)]), make_entry([(2, 60)], event_ids=[])])

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_CONSERVATION)
        assert len(issues) == 1
        assert issues[0].block_id == 1
        assert "over-allocated" in issues[0].detail
        assert "time was invented" in issues[0].detail

    def test_conservation_counts_entries_and_residual_together(self):
        """Splitting a block between an entry and residual conserves it; neither half alone would."""
        draft = WorkLogDraft(
            entries=[make_entry([(1, 30)]), make_entry([(2, 60)], event_ids=[])],
            residual_unassigned_minutes=residual((1, 60)),
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert result.passed
        assert checks_of(result, CHECK_CONSERVATION) == []

    def test_a_short_block_allocated_its_real_duration_is_not_flagged(self):
        """The sub-30-minute exemption: a 20 min block may stand as its own entry at its real 20 min."""
        evidence = build_evidence([], [make_block(project="scratch-notes", start_hour=16, minutes=20)], [])
        draft = WorkLogDraft(entries=[make_entry([(1, 20)], event_ids=[])])

        result = verify_draft(draft, evidence)

        assert result.passed
        assert result.issues == []

    def test_a_short_block_padded_up_to_the_thirty_minute_floor_is_an_error(self):
        """The exemption lets a short block stand alone; it never licenses rounding it up to the minimum."""
        evidence = build_evidence([], [make_block(project="scratch-notes", start_hour=16, minutes=20)], [])
        draft = WorkLogDraft(entries=[make_entry([(1, 30)], event_ids=[])])

        result = verify_draft(draft, evidence)

        assert not result.passed
        issues = checks_of(result, CHECK_CONSERVATION)
        assert len(issues) == 1
        assert issues[0].block_id == 1
        assert "over-allocated" in issues[0].detail
        assert "10 min discrepancy" in issues[0].detail


class TestIdCrossCheck:
    def test_allocating_to_a_block_id_that_never_existed_is_an_error(self):
        draft = WorkLogDraft(
            entries=[make_entry([(1, 90)]), make_entry([(2, 60), (7, 45)], event_ids=[])],
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_UNKNOWN_ID)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].block_id == 7
        assert issues[0].entry_index == 1
        assert "never in the evidence" in issues[0].detail

    def test_an_unknown_block_id_in_residual_is_an_error_naming_residual(self):
        draft = WorkLogDraft(
            entries=[make_entry([(1, 90)]), make_entry([(2, 60)], event_ids=[])],
            residual_unassigned_minutes=residual((9, 15)),
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_UNKNOWN_ID)
        assert len(issues) == 1
        assert issues[0].block_id == 9
        assert issues[0].entry_index is None
        assert "residual_unassigned_minutes" in issues[0].detail

    def test_citing_a_remote_event_that_was_never_in_the_evidence_is_an_error(self):
        """The worst failure mode: a fabricated citation makes a guess look like proof."""
        draft = WorkLogDraft(
            entries=[
                make_entry([(1, 90)], event_ids=["gh:pr:41", "gh:pr:999"]),
                make_entry([(2, 60)], event_ids=[]),
            ],
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_UNKNOWN_ID)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].entry_index == 0
        assert "gh:pr:999" in issues[0].detail
        assert "fabricated citation" in issues[0].detail

    def test_a_reminder_citing_an_unknown_remote_event_is_an_error(self):
        draft = WorkLogDraft(
            entries=[make_entry([(1, 90)]), make_entry([(2, 60)], event_ids=[])],
            reminders=[make_reminder(["JIRA-NOPE"])],
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_UNKNOWN_ID)
        assert len(issues) == 1
        assert "reminder 0" in issues[0].detail
        assert "JIRA-NOPE" in issues[0].detail

    def test_a_citation_of_a_real_unmatched_event_is_accepted(self):
        """Unmatched events are part of the evidence too, so citing one is not a fabrication."""
        evidence = build_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[make_event()])],
            [],
            [make_event(external_id="ABC-99", source="jira", project="ABC", hour=17)],
        )
        draft = WorkLogDraft(
            entries=[make_entry([(1, 90)], event_ids=["gh:pr:41", "ABC-99"])],
            reminders=[make_reminder(["ABC-99"])],
        )

        result = verify_draft(draft, evidence)

        assert result.passed
        assert result.issues == []


class TestCompletenessCheck:
    def test_a_block_appearing_nowhere_at_all_is_an_error(self):
        draft = WorkLogDraft(entries=[make_entry([(1, 90)])])

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_COMPLETENESS)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].block_id == 2
        assert "silently dropped" in issues[0].detail
        assert "60 min measured" in issues[0].detail

    def test_a_dropped_block_is_reported_by_conservation_as_well(self):
        """The two checks answer different questions, so one defect deliberately surfaces under both names."""
        draft = WorkLogDraft(entries=[make_entry([(1, 90)])])

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        conservation = checks_of(result, CHECK_CONSERVATION)
        assert len(conservation) == 1
        assert conservation[0].block_id == 2
        assert "0 min charged" in conservation[0].detail

    def test_a_block_in_both_an_entry_and_residual_is_a_warning_not_an_error(self):
        """Partly attributed and partly not is an honest split, so it must not fail the draft."""
        draft = WorkLogDraft(
            entries=[make_entry([(1, 30)]), make_entry([(2, 60)], event_ids=[])],
            residual_unassigned_minutes=residual((1, 60)),
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert result.passed
        issues = checks_of(result, CHECK_COMPLETENESS)
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].block_id == 1
        assert errors_of(result) == []


class TestCrossEntryDuplicateCheck:
    def test_charging_one_block_fully_in_two_separate_entries_is_an_error(self):
        """`DraftEntry`'s own validator cannot see this -- it only ever inspects one entry at a time."""
        draft = WorkLogDraft(
            entries=[
                make_entry([(1, 90)]),
                make_entry([(1, 90)], event_ids=[]),
                make_entry([(2, 60)], event_ids=[]),
            ],
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        issues = checks_of(result, CHECK_CROSS_ENTRY_DUPLICATE)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].block_id == 1
        assert "entry 0 charges 90 min" in issues[0].detail
        assert "entry 1 charges 90 min" in issues[0].detail
        assert "counted more than once" in issues[0].detail

    def test_the_within_entry_duplicate_this_complements_is_still_rejected_by_the_schema(self):
        """Guards the division of labour: F1's within-entry check is what makes this one only need cross-entry."""
        with pytest.raises(ValidationError):
            make_entry([(1, 45), (1, 45)])

    def test_a_block_split_across_entries_within_its_measured_total_is_not_flagged(self):
        draft = WorkLogDraft(entries=[make_entry([(1, 50)]), make_entry([(1, 40), (2, 60)])])

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert checks_of(result, CHECK_CROSS_ENTRY_DUPLICATE) == []

    def test_an_overcharge_inside_a_single_entry_is_not_reported_as_a_cross_entry_defect(self):
        """One entry charging block 1 for 120 min is a conservation failure, but nothing was spread across entries."""
        draft = WorkLogDraft(entries=[make_entry([(1, 120)]), make_entry([(2, 60)], event_ids=[])])

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert checks_of(result, CHECK_CROSS_ENTRY_DUPLICATE) == []
        assert checks_of(result, CHECK_CONSERVATION) != []


class TestReminderSanityCheck:
    def test_two_reminders_covering_the_same_event_are_a_warning(self):
        """Stage 5 deliberately does not dedupe the merge, so both agreeing is a signal worth surfacing."""
        evidence = build_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[make_event()])],
            [],
            [make_event(external_id="ABC-99", source="jira", project="ABC", hour=17)],
        )
        draft = WorkLogDraft(
            entries=[make_entry([(1, 90)])],
            reminders=[
                make_reminder(["ABC-99"], note="Unlogged jira activity on ABC: LOG-212 moved to Done"),
                make_reminder(["ABC-99"], note="Which project does the Jira transition belong to?"),
            ],
        )

        result = verify_draft(draft, evidence)

        assert result.passed, "a duplicated reminder is for review, not a correctness failure"
        issues = checks_of(result, CHECK_DUPLICATE_REMINDER)
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert "ABC-99" in issues[0].detail
        assert "indices 0, 1" in issues[0].detail

    def test_neither_duplicate_reminder_is_dropped_from_the_draft(self):
        """Verification reports; it never repairs. Both reminders must still be there afterwards."""
        evidence = build_evidence(
            [], [], [make_event(external_id="ABC-99", source="jira", project="ABC", hour=17)]
        )
        draft = WorkLogDraft(reminders=[make_reminder(["ABC-99"]), make_reminder(["ABC-99"])])

        verify_draft(draft, evidence)

        assert len(draft.reminders) == 2

    def test_reminders_covering_different_events_are_not_flagged(self):
        evidence = build_evidence(
            [],
            [],
            [
                make_event(external_id="ABC-99", source="jira", project="ABC", hour=17),
                make_event(external_id="ABC-100", source="jira", project="ABC", hour=18),
            ],
        )
        draft = WorkLogDraft(reminders=[make_reminder(["ABC-99"]), make_reminder(["ABC-100"])])

        result = verify_draft(draft, evidence)

        assert result.passed
        assert result.issues == []

    def test_one_reminder_repeating_an_id_in_its_own_list_is_not_a_duplicate(self):
        """The check is about two reminders asking the same thing, not about one reminder's own list."""
        evidence = build_evidence(
            [], [], [make_event(external_id="ABC-99", source="jira", project="ABC", hour=17)]
        )
        draft = WorkLogDraft(reminders=[make_reminder(["ABC-99", "ABC-99"])])

        result = verify_draft(draft, evidence)

        assert checks_of(result, CHECK_DUPLICATE_REMINDER) == []


# Stage 5's live run, reconstructed from the fixtures in test_reconciliation_live.py: 115 + 50 + 20 = 185
# measured minutes across three blocks, two of them corroborated by GitHub events, plus one unmatched Jira
# ticket carried by a pre-built reminder.
LIVE_EVIDENCE = build_evidence(
    [
        MatchedGroup(
            block=make_block(project="logline", start_hour=9, minutes=115, apps=("vscode", "terminal")),
            events=[
                make_event(external_id="gh:pr:41", summary="Add Phase 4 AI reconciliation output schema"),
                make_event(external_id="gh:push:8f21c", hour=10, summary="Harden DraftEntry validators"),
            ],
        ),
        MatchedGroup(
            block=make_block(project="logline", start_hour=13, start_minute=30, minutes=50, apps=("chrome",)),
            events=[make_event(external_id="gh:review:770", hour=13, summary="Review comments on #40")],
        ),
    ],
    [make_block(project="scratch-notes", start_hour=16, start_minute=10, minutes=20, apps=("obsidian",))],
    [make_event(external_id="ABC-99", source="jira", project="ABC", hour=17, summary="LOG-212 moved to Done")],
)

LIVE_TOTAL_MEASURED_MINUTES = 185


class TestAgainstStageFivesRealLiveRun:
    """The stronger proof: a real correct draft over real Stage 5 evidence must pass, not just synthetic ones."""

    def _live_draft(self):
        return WorkLogDraft(
            entries=[
                make_entry(
                    [(1, 115)],
                    event_ids=["gh:pr:41", "gh:push:8f21c"],
                    description="Implemented the Phase 4 reconciliation output schema and hardened its validators",
                ),
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=2, minutes=50)],
                    tag=EntryTag.code_review,
                    description="Reviewed pull request #40",
                    source_remote_event_ids=["gh:review:770"],
                ),
                DraftEntry(
                    date=DAY,
                    project="scratch-notes",
                    allocations=[BlockAllocation(block_id=3, minutes=20)],
                    tag=EntryTag.documentation,
                    description="Note-taking in Obsidian",
                    source_remote_event_ids=[],
                ),
            ],
            reminders=[
                make_reminder(
                    ["ABC-99"], note="Unlogged jira activity on ABC: LOG-212 moved to Done"
                )
            ],
        )

    def test_the_reconstructed_evidence_matches_the_live_runs_three_blocks(self):
        assert set(LIVE_EVIDENCE.blocks_by_id) == {1, 2, 3}
        assert LIVE_EVIDENCE.remote_event_ids == {"gh:pr:41", "gh:push:8f21c", "gh:review:770", "ABC-99"}

    def test_a_correct_draft_over_the_real_live_evidence_passes_with_zero_issues(self):
        result = verify_draft(self._live_draft(), LIVE_EVIDENCE)

        assert result.passed
        assert result.issues == [], f"a correct real draft was flagged: {[i.detail for i in result.issues]}"

    def test_the_whole_measured_day_is_accounted_for(self):
        draft = self._live_draft()
        allocated = sum(a.minutes for e in draft.entries for a in e.allocations)

        assert allocated == LIVE_TOTAL_MEASURED_MINUTES

    def test_losing_a_single_minute_of_the_real_day_is_caught(self):
        """Sanity-check the fixture is actually load-bearing rather than passing for some unrelated reason."""
        draft = self._live_draft()
        draft.entries[0].allocations[0].minutes = 114

        result = verify_draft(draft, LIVE_EVIDENCE)

        assert not result.passed
        assert any(issue.block_id == 1 and "1 min discrepancy" in issue.detail for issue in result.issues)


class TestScopeIsStructuralNotJudgmental:
    def test_an_entry_with_no_review_reason_and_no_citations_is_not_an_error(self):
        """Observed in Stage 5's live run. That is a prompt-quality concern, not a verification failure."""
        draft = WorkLogDraft(
            entries=[
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=1, minutes=90)],
                    tag=EntryTag.coding,
                    description="Worked on logline",
                    source_remote_event_ids=[],
                    review_reason=None,
                ),
                make_entry([(2, 60)], event_ids=[]),
            ],
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert result.passed
        assert result.issues == [], "verification must not judge citation or review-reason quality"

    def test_a_vague_description_is_not_an_error(self):
        draft = WorkLogDraft(
            entries=[make_entry([(1, 90)], description="stuff"), make_entry([(2, 60)], event_ids=[])],
        )

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert result.passed

    def test_an_empty_draft_against_no_evidence_passes(self):
        result = verify_draft(WorkLogDraft(), build_evidence([], [], []))

        assert result.passed
        assert result.issues == []

    def test_an_empty_draft_against_real_evidence_fails_on_every_block(self):
        result = verify_draft(WorkLogDraft(), SIMPLE_EVIDENCE)

        assert not result.passed
        assert {issue.block_id for issue in checks_of(result, CHECK_COMPLETENESS)} == {1, 2}


class TestVerificationNeverRepairs:
    def test_a_broken_draft_is_returned_untouched(self):
        draft = WorkLogDraft(entries=[make_entry([(1, 500)])], residual_unassigned_minutes=residual((9, 15)))
        before = draft.model_dump()

        result = verify_draft(draft, SIMPLE_EVIDENCE)

        assert not result.passed
        assert draft.model_dump() == before, "verify_draft must report, never correct"
