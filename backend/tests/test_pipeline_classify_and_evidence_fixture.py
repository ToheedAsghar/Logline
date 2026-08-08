"""End-to-end fixture proving the classify-before-aggregate pipeline fix against the real scenario that
motivated it: a day with a meeting, concurrent multitasking during that meeting, a browser-only session with
no project, and local-only coding work with no remote evidence at all.

This drives the real functions from every touched stage -- `classify_session`, `aggregate_local_activity`,
`match_local_blocks_to_remote_events`, `build_evidence`, `verify_draft` -- the same functions
`_gather_evidence`/`reconcile_evidence` call in production, just without the DB/HTTP layer (which is already
covered by `tests/test_reconciliation_router.py`). No LLM call is made here; the "correct draft" is
hand-built to prove the pipeline stages *can* represent this day correctly and that verification accepts it
-- the actual live-model comparison is a separate, real-data run against 2026-08-06 (see the PR description).

The fixture below is a compressed version of the real day (minutes scaled down so assertions stay legible),
not the literal real timestamps.
"""

import json
from datetime import date, datetime, timezone

from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.schemas import BlockAllocation, DraftEntry, EntryTag, WorkLogDraft
from app.agent.reconciliation.verifier import CHECK_CONSERVATION, verify_draft
from app.local_activity.aggregation import RawSessionRow, aggregate_local_activity
from app.local_activity.classification import SessionCategory, classify_session
from app.matching.matcher import RemoteEventData, ResolvedLocalBlock, match_local_blocks_to_remote_events

UTC = timezone.utc
DAY = date(2026, 8, 6)


def _t(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 6, hour, minute, tzinfo=UTC)


RAW_SESSIONS = [
    dict(
        bundle_id="com.google.Chrome",
        app_name="Google Chrome",
        window_title="Meet - Design Review",
        project_path=None,
        context_detail=json.dumps({"is_meeting": True, "meeting_name": "Design Review", "browser": "Chrome"}),
        started_at=_t(9, 0),
        ended_at=_t(9, 5),
    ),
    dict(
        bundle_id="com.microsoft.VSCode",
        app_name="VS Code",
        window_title="auth.py — logline",
        project_path="/Users/dev/logline",
        context_detail=None,
        started_at=_t(9, 5),
        ended_at=_t(9, 30),
    ),
    dict(
        bundle_id="com.google.Chrome",
        app_name="Google Chrome",
        window_title="Meet - Design Review",
        project_path=None,
        context_detail=json.dumps({"is_meeting": True, "meeting_name": "Design Review", "browser": "Chrome"}),
        started_at=_t(9, 30),
        ended_at=_t(10, 0),
    ),
    dict(
        bundle_id="com.google.Chrome",
        app_name="Google Chrome",
        window_title="Add title digest by toheed · Pull Request #58 · ToheedAsghar/Logline · GitHub",
        project_path=None,
        context_detail=json.dumps({"url": "https://github.com/ToheedAsghar/Logline/pull/58", "browser": "Chrome"}),
        started_at=_t(10, 0),
        ended_at=_t(10, 20),
    ),
    dict(
        bundle_id="com.microsoft.VSCode",
        app_name="VS Code",
        window_title="scratch.py — scratch-project",
        project_path="/Users/dev/scratch-project",
        context_detail=None,
        started_at=_t(10, 20),
        ended_at=_t(11, 20),
    ),
]

CALENDAR_EVENT = RemoteEventData(
    external_id="cal:evt:1",
    source="calendar",
    remote_project_id=None,
    occurred_at=_t(9, 0),
    event_type="meeting",
    summary="Design Review",
)


def _classify_and_build_rows() -> list[RawSessionRow]:
    rows = []
    for session in RAW_SESSIONS:
        classification = classify_session(
            bundle_id=session["bundle_id"],
            window_title=session["window_title"],
            project_path=session["project_path"],
            context_detail=session["context_detail"],
        )
        rows.append(
            RawSessionRow(
                project=session["project_path"],
                app=session["app_name"],
                start_time=session["started_at"],
                end_time=session["ended_at"],
                category=classification.category,
                window_title=session["window_title"],
                meeting_name=classification.meeting_name,
            )
        )
    return rows


class TestOldPipelineWouldHaveDroppedMostOfTheDay:
    """Reproduces the old `project_path IS NOT NULL` filter directly, to prove -- against this exact
    fixture -- that it silently discarded roughly half the real day, all of it browser-based."""

    def test_project_path_filter_drops_the_meeting_and_the_browser_only_review(self):
        surviving = [session for session in RAW_SESSIONS if session["project_path"] is not None]

        assert len(surviving) == 2
        dropped_minutes = sum(
            (session["ended_at"] - session["started_at"]).total_seconds() / 60
            for session in RAW_SESSIONS
            if session["project_path"] is None
        )
        kept_minutes = sum(
            (session["ended_at"] - session["started_at"]).total_seconds() / 60 for session in surviving
        )

        assert dropped_minutes == 55
        assert kept_minutes == 85
        assert kept_minutes / (kept_minutes + dropped_minutes) < 0.65


class TestNewPipelineClassifiesAggregatesAndMatchesTheWholeDay:
    def test_nothing_is_dropped_every_minute_of_the_day_becomes_a_block(self):
        """165 = meeting span (60, spanning the coding interruption) + concurrent coding (25) + browser PR
        review (20) + local-only coding (60). This exceeds the day's 140 real elapsed minutes on purpose --
        the 25-minute excess is the legitimate double-booked overlap between the meeting and the coding that
        happened during it, not lost or invented time."""
        rows = _classify_and_build_rows()

        blocks = aggregate_local_activity(rows)

        total_minutes = sum(round(block.duration.total_seconds() / 60) for block in blocks)
        assert total_minutes == 165

    def test_the_meeting_spans_the_full_call_despite_the_mid_call_interruption(self):
        rows = _classify_and_build_rows()

        blocks = aggregate_local_activity(rows)

        meeting_blocks = [block for block in blocks if block.category == SessionCategory.meeting]
        assert len(meeting_blocks) == 1
        assert meeting_blocks[0].start_time == _t(9, 0)
        assert meeting_blocks[0].end_time == _t(10, 0)

    def test_the_concurrent_coding_block_is_separate_from_and_overlaps_the_meeting(self):
        rows = _classify_and_build_rows()

        blocks = aggregate_local_activity(rows)

        coding_blocks = [
            block
            for block in blocks
            if block.category == SessionCategory.coding and block.project == "/Users/dev/logline"
        ]
        assert len(coding_blocks) == 1
        coding_block = coding_blocks[0]
        meeting_block = next(block for block in blocks if block.category == SessionCategory.meeting)
        assert coding_block.start_time < meeting_block.end_time
        assert meeting_block.start_time < coding_block.end_time

    def test_the_browser_only_review_becomes_its_own_block_with_no_project(self):
        rows = _classify_and_build_rows()

        blocks = aggregate_local_activity(rows)

        review_blocks = [block for block in blocks if block.category == SessionCategory.code_review]
        assert len(review_blocks) == 1
        assert review_blocks[0].project is None
        assert round(review_blocks[0].duration.total_seconds() / 60) == 20

    def test_the_meeting_block_matches_the_calendar_event_by_time_alone(self):
        rows = _classify_and_build_rows()
        blocks = aggregate_local_activity(rows)

        resolved = [ResolvedLocalBlock(block=block, remote_identities={}) for block in blocks]
        result = match_local_blocks_to_remote_events(resolved, [CALENDAR_EVENT])

        matched_meeting_groups = [group for group in result.matched if group.block.category == SessionCategory.meeting]
        assert len(matched_meeting_groups) == 1
        assert matched_meeting_groups[0].events == [CALENDAR_EVENT]


class TestACorrectDraftForThisDayPassesVerification:
    def _evidence_and_block_ids(self):
        rows = _classify_and_build_rows()
        blocks = aggregate_local_activity(rows)
        resolved = [ResolvedLocalBlock(block=block, remote_identities={}) for block in blocks]
        match_result = match_local_blocks_to_remote_events(resolved, [CALENDAR_EVENT])
        evidence = build_evidence(match_result.matched, match_result.unmatched_blocks, match_result.unmatched_events)

        by_category = {block.category: block_id for block_id, block in evidence.blocks_by_id.items()}
        return evidence, by_category

    def test_charging_every_block_its_own_full_measured_minutes_passes_with_no_errors(self):
        """This is the shape a correct model response takes: the meeting and the concurrent coding block
        are each charged their own full measured minutes in separate entries -- neither shrinks to make
        room for the other, which is exactly what rule 8 of the prompt requires and what the old strict
        single-booking conservation check would have wrongly rejected."""
        evidence, by_category = self._evidence_and_block_ids()
        meeting_id = by_category[SessionCategory.meeting]
        coding_logline_id = next(
            block_id
            for block_id, block in evidence.blocks_by_id.items()
            if block.category == SessionCategory.coding and block.project == "/Users/dev/logline"
        )
        review_id = by_category[SessionCategory.code_review]
        coding_scratch_id = next(
            block_id
            for block_id, block in evidence.blocks_by_id.items()
            if block.category == SessionCategory.coding and block.project == "/Users/dev/scratch-project"
        )

        draft = WorkLogDraft(
            entries=[
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=meeting_id, minutes=60)],
                    tag=EntryTag.meeting,
                    description="Design Review",
                    source_remote_event_ids=["cal:evt:1"],
                ),
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=coding_logline_id, minutes=25)],
                    tag=EntryTag.coding,
                    description="Logline - Auth work: Development session in VS Code on auth.py.",
                    review_reason="Overlaps the Design Review meeting; charged independently per rule 8.",
                ),
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=review_id, minutes=20)],
                    tag=EntryTag.code_review,
                    description="Logline - PR review: Reviewed pull request #58 in the browser.",
                ),
                DraftEntry(
                    date=DAY,
                    project="scratch-project",
                    allocations=[BlockAllocation(block_id=coding_scratch_id, minutes=60)],
                    tag=EntryTag.coding,
                    description="Scratch-project - Development: Session in VS Code on scratch.py.",
                    review_reason="No commit, PR, or ticket activity found during this block.",
                ),
            ]
        )

        result = verify_draft(draft, evidence)

        assert result.passed, [issue.detail for issue in result.issues]
        assert result.issues == []

    def test_shrinking_the_meeting_to_make_room_for_the_overlap_still_fails_conservation(self):
        """Proves the new invariant did not become "anything goes": it permits the overlap to exist, but
        each block's own measured minutes still must be charged in full -- moving minutes between the two
        overlapping blocks is still a conservation violation, not a legitimate way to resolve the overlap."""
        evidence, by_category = self._evidence_and_block_ids()
        meeting_id = by_category[SessionCategory.meeting]
        coding_logline_id = next(
            block_id
            for block_id, block in evidence.blocks_by_id.items()
            if block.category == SessionCategory.coding and block.project == "/Users/dev/logline"
        )
        review_id = by_category[SessionCategory.code_review]
        coding_scratch_id = next(
            block_id
            for block_id, block in evidence.blocks_by_id.items()
            if block.category == SessionCategory.coding and block.project == "/Users/dev/scratch-project"
        )

        draft = WorkLogDraft(
            entries=[
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=meeting_id, minutes=35)],
                    tag=EntryTag.meeting,
                    description="Design Review",
                ),
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=coding_logline_id, minutes=25)],
                    tag=EntryTag.coding,
                    description="Logline - Auth work.",
                ),
                DraftEntry(
                    date=DAY,
                    project="logline",
                    allocations=[BlockAllocation(block_id=review_id, minutes=20)],
                    tag=EntryTag.code_review,
                    description="Logline - PR review.",
                ),
                DraftEntry(
                    date=DAY,
                    project="scratch-project",
                    allocations=[BlockAllocation(block_id=coding_scratch_id, minutes=60)],
                    tag=EntryTag.coding,
                    description="Scratch-project - Development.",
                ),
            ]
        )

        result = verify_draft(draft, evidence)

        assert not result.passed
        conservation_issues = [issue for issue in result.issues if issue.check == CHECK_CONSERVATION]
        assert len(conservation_issues) == 1
        assert conservation_issues[0].block_id == meeting_id
