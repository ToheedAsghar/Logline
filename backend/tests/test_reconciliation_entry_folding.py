"""Test the final-entry minimum floor and where sub-floor entries are folded."""

from datetime import datetime, timedelta, timezone

from app.agent.reconciliation.entries import fold_small_entries, form_entries
from app.agent.reconciliation.evidence import build_evidence
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory

UTC = timezone.utc


def make_block(
    project="logline",
    start_hour=9,
    start_minute=0,
    minutes=90,
    category=SessionCategory.coding,
    topic=None,
    meeting_name=None,
):
    start = datetime(2026, 8, 6, start_hour, 0, tzinfo=UTC) + timedelta(minutes=start_minute)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration,
        apps=["vscode"], category=category, deterministic_topic=topic, meeting_name=meeting_name,
    )


def fold(blocks):
    bundle = build_evidence([], blocks, [])
    return fold_small_entries(form_entries(bundle), bundle), bundle


class TestTheFloorLeavesNormalEntriesAlone:
    def test_entries_above_the_floor_are_untouched(self):
        blocks = [make_block(minutes=90), make_block(project="other", minutes=60, start_hour=13)]

        folding, _ = fold(blocks)

        assert len(folding.entries) == 2
        assert folding.residual == []

    def test_total_minutes_are_conserved_across_folding(self):
        blocks = [
            make_block(minutes=90, topic=("files", "a.py")),
            make_block(minutes=2, start_hour=11, topic=("files", "a.py")),
        ]

        folding, bundle = fold(blocks)

        charged = sum(a.minutes for e in folding.entries for a in e.allocations)
        charged += sum(a.minutes for a in folding.residual)
        assert charged == sum(round(b.duration.total_seconds() / 60) for b in bundle.blocks_by_id.values())


class TestFoldingBySharedTopic:
    def test_a_sub_floor_entry_joins_the_entry_sharing_its_topic(self):
        blocks = [
            make_block(minutes=90, topic=("pr", "36"), category=SessionCategory.coding),
            make_block(minutes=2, start_hour=14, topic=("pr", "36"), category=SessionCategory.code_review),
        ]

        folding, _ = fold(blocks)

        assert len(folding.entries) == 1
        assert folding.entries[0].total_minutes == 92
        assert folding.residual == []

    def test_shared_topic_wins_over_a_nearer_entry_of_the_same_kind(self):
        blocks = [
            make_block(minutes=90, start_hour=9, topic=("pr", "36"), category=SessionCategory.coding),
            make_block(minutes=60, start_hour=13, topic=("files", "x.py"), category=SessionCategory.code_review),
            make_block(minutes=2, start_hour=14, topic=("pr", "36"), category=SessionCategory.code_review),
        ]

        folding, _ = fold(blocks)

        by_topic = {e.topic: e.total_minutes for e in folding.entries}
        assert by_topic[("pr", "36")] == 92


class TestFoldingByProjectAndCategory:
    def test_a_sub_floor_entry_joins_the_nearest_entry_of_the_same_kind(self):
        blocks = [
            make_block(minutes=60, start_hour=9, topic=("files", "early.py")),
            make_block(minutes=60, start_hour=16, topic=("files", "late.py")),
            make_block(minutes=2, start_hour=15, topic=("files", "stray.py")),
        ]

        folding, _ = fold(blocks)

        absorbed = next(e for e in folding.entries if e.topic == ("files", "late.py"))
        assert absorbed.total_minutes == 62

    def test_a_different_project_is_not_a_fold_target(self):
        blocks = [
            make_block(project="logline", minutes=90),
            make_block(project="other-repo", minutes=2, start_hour=15, category=SessionCategory.comms),
        ]

        folding, _ = fold(blocks)

        assert [a.minutes for a in folding.residual] == [2]


class TestMeetingsAreExemptInBothDirections:
    def test_a_short_meeting_is_never_folded_away(self):
        blocks = [
            make_block(minutes=90),
            make_block(minutes=2, start_hour=13, category=SessionCategory.meeting, meeting_name="Standup"),
        ]

        folding, _ = fold(blocks)

        meetings = [e for e in folding.entries if e.category == SessionCategory.meeting]
        assert len(meetings) == 1
        assert meetings[0].total_minutes == 2

    def test_a_meeting_never_absorbs_other_work(self):
        blocks = [
            make_block(minutes=60, start_hour=9, category=SessionCategory.meeting, meeting_name="Standup"),
            make_block(minutes=2, start_hour=9, start_minute=70, category=SessionCategory.comms, project="other"),
        ]

        folding, _ = fold(blocks)

        meeting = next(e for e in folding.entries if e.category == SessionCategory.meeting)
        assert meeting.total_minutes == 60
        assert [a.minutes for a in folding.residual] == [2]


class TestResidual:
    def test_an_orphaned_sub_floor_entry_becomes_residual(self):
        blocks = [make_block(project="only-thing", minutes=2, category=SessionCategory.comms)]

        folding, _ = fold(blocks)

        assert folding.entries == []
        assert [a.minutes for a in folding.residual] == [2]

    def test_residual_cites_the_real_block_id(self):
        blocks = [make_block(project="only-thing", minutes=2, category=SessionCategory.comms)]

        folding, bundle = fold(blocks)

        assert folding.residual[0].block_id in bundle.blocks_by_id
