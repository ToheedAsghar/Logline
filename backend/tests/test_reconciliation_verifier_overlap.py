"""Tests for _check_unexplained_overlap (app/agent/reconciliation/verifier.py).

`tests/test_reconciliation_verifier.py` covers the original five checks unchanged; this file covers only the
new one. Overlapping blocks are allowed by design -- a Meeting block's span can legitimately cover a
concurrent workstream's own block, and each is still charged its own full measured minutes independently
(conservation is untouched by this check). What must never happen is two *non*-Meeting blocks overlapping,
which would mean a classification or aggregation bug is silently inflating the day's total tracked minutes.
"""

from datetime import date, datetime, timedelta, timezone

from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.schemas import BlockAllocation, DraftEntry, EntryTag, WorkLogDraft
from app.agent.reconciliation.verifier import CHECK_UNEXPLAINED_OVERLAP, verify_draft
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory
from app.matching.matcher import MatchedGroup

UTC = timezone.utc
DAY = date(2026, 8, 6)


def make_block(start_hour=9, start_minute=0, minutes=60, project="logline", category=SessionCategory.coding):
    start = datetime(2026, 8, 6, start_hour, start_minute, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration, apps=["vscode"],
        category=category,
    )


def make_entry(allocations, tag=EntryTag.coding, description="Work"):
    return DraftEntry(
        date=DAY,
        project="logline",
        allocations=[BlockAllocation(block_id=block_id, minutes=minutes) for block_id, minutes in allocations],
        tag=tag,
        description=description,
    )


def overlap_issues(result):
    return [issue for issue in result.issues if issue.check == CHECK_UNEXPLAINED_OVERLAP]


class TestLegitimateOverlapInvolvingAMeeting:
    def test_meeting_and_concurrent_coding_block_overlap_without_an_issue(self):
        meeting = make_block(start_hour=9, minutes=60, project=None, category=SessionCategory.meeting)
        coding = make_block(
            start_hour=9, start_minute=10, minutes=25, project="logline", category=SessionCategory.coding
        )

        evidence = build_evidence([], [meeting, coding], [])
        draft = WorkLogDraft(
            entries=[
                make_entry([(1, 60)], tag=EntryTag.meeting, description="Design Review"),
                make_entry([(2, 25)], tag=EntryTag.coding),
            ]
        )

        result = verify_draft(draft, evidence)

        assert overlap_issues(result) == []
        assert result.passed

    def test_order_of_meeting_vs_non_meeting_block_id_does_not_matter(self):
        """Same scenario with the non-Meeting block assigned the lower id, to prove the check isn't
        accidentally order-sensitive."""
        coding = make_block(start_hour=9, minutes=25, project="logline", category=SessionCategory.coding)
        meeting = make_block(start_hour=9, minutes=60, project=None, category=SessionCategory.meeting)

        evidence = build_evidence([], [coding, meeting], [])
        draft = WorkLogDraft(
            entries=[
                make_entry([(1, 25)], tag=EntryTag.coding),
                make_entry([(2, 60)], tag=EntryTag.meeting, description="Design Review"),
            ]
        )

        result = verify_draft(draft, evidence)

        assert overlap_issues(result) == []


class TestIllegitimateOverlap:
    def test_two_non_meeting_blocks_overlapping_is_an_error(self):
        first = make_block(start_hour=9, minutes=60, project="logline", category=SessionCategory.coding)
        second = make_block(
            start_hour=9, start_minute=10, minutes=20, project="other-repo", category=SessionCategory.coding
        )

        evidence = build_evidence([], [first, second], [])
        draft = WorkLogDraft(entries=[make_entry([(1, 60)]), make_entry([(2, 20)])])

        result = verify_draft(draft, evidence)

        issues = overlap_issues(result)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert not result.passed

    def test_non_overlapping_non_meeting_blocks_carry_no_issue(self):
        first = make_block(start_hour=9, minutes=30, category=SessionCategory.coding)
        second = make_block(start_hour=14, minutes=30, category=SessionCategory.comms)

        evidence = build_evidence([], [first, second], [])
        draft = WorkLogDraft(entries=[make_entry([(1, 30)]), make_entry([(2, 30)])])

        result = verify_draft(draft, evidence)

        assert overlap_issues(result) == []

    def test_three_way_overlap_reports_only_the_pair_missing_a_meeting(self):
        """Block 1 (Meeting) overlaps both 2 and 3 legitimately; 2 and 3 (both Coding) also overlap each
        other, which is the one illegitimate pair and the only one that should be reported."""
        meeting = make_block(start_hour=9, minutes=60, project=None, category=SessionCategory.meeting)
        coding_a = make_block(
            start_hour=9, start_minute=5, minutes=30, project="logline", category=SessionCategory.coding
        )
        coding_b = make_block(
            start_hour=9, start_minute=10, minutes=30, project="other-repo", category=SessionCategory.coding
        )

        evidence = build_evidence([], [meeting, coding_a, coding_b], [])
        draft = WorkLogDraft(
            entries=[
                make_entry([(1, 60)], tag=EntryTag.meeting, description="Design Review"),
                make_entry([(2, 30)]),
                make_entry([(3, 30)]),
            ]
        )

        result = verify_draft(draft, evidence)

        issues = overlap_issues(result)
        assert len(issues) == 1
        assert {issues[0].block_id} <= {2, 3}


class TestOverlapIndependentOfEntryStructure:
    def test_overlap_is_flagged_even_when_conservation_and_completeness_otherwise_pass(self):
        """Confirms this is a genuinely separate check, not a side effect of another one -- a draft that is
        otherwise perfectly correct still gets flagged if it has an unexplained overlap in its evidence."""
        first = make_block(start_hour=9, minutes=45, category=SessionCategory.coding)
        second = make_block(start_hour=9, start_minute=20, minutes=15, category=SessionCategory.documentation)

        evidence = build_evidence(
            [MatchedGroup(block=first, events=[])], [second], []
        )
        draft = WorkLogDraft(entries=[make_entry([(1, 45)]), make_entry([(2, 15)], tag=EntryTag.documentation)])

        result = verify_draft(draft, evidence)

        from app.agent.reconciliation.verifier import CHECK_COMPLETENESS, CHECK_CONSERVATION

        assert [issue for issue in result.issues if issue.check == CHECK_CONSERVATION] == []
        assert [issue for issue in result.issues if issue.check == CHECK_COMPLETENESS] == []
        assert len(overlap_issues(result)) == 1
        assert not result.passed
