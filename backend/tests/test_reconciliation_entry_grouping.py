"""Test minority-category merging and session-bounded merging of adjacent entries."""

from datetime import datetime, timedelta, timezone

from app.agent.reconciliation.constants import ENTRY_MERGE_MAX_SPAN_MINUTES
from app.agent.reconciliation.entries import form_entries, merge_adjacent_entries
from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.schemas import EntryTag
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory

UTC = timezone.utc


def make_block(
    project="logline",
    start_hour=9,
    start_minute=0,
    minutes=60,
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


def group(blocks):
    bundle = build_evidence([], blocks, [])
    return merge_adjacent_entries(form_entries(bundle), bundle), bundle


def categories_of(entry, bundle):
    return {bundle.blocks_by_id[block_id].category for block_id in entry.block_ids}


class TestMinorityCategoryMerging:
    def test_a_small_minority_category_joins_the_dominant_one(self):
        topic = ("branch", "feature/sso")
        blocks = [
            make_block(minutes=90, topic=topic, category=SessionCategory.coding),
            make_block(start_hour=11, minutes=30, topic=topic, category=SessionCategory.code_review),
        ]

        entries, bundle = group(blocks)

        assert len(entries) == 1
        assert entries[0].total_minutes == 120
        assert entries[0].category == SessionCategory.coding
        assert entries[0].base_tag == EntryTag.coding

    def test_an_even_split_stays_two_entries(self):
        topic = ("branch", "feature/sso")
        blocks = [
            make_block(minutes=60, topic=topic, category=SessionCategory.coding),
            make_block(start_hour=11, minutes=60, topic=topic, category=SessionCategory.code_review),
        ]

        entries, _ = group(blocks)

        assert len(entries) == 2

    def test_entries_without_a_topic_never_merge_across_categories(self):
        blocks = [
            make_block(minutes=90, topic=None, category=SessionCategory.coding),
            make_block(start_hour=11, minutes=10, topic=None, category=SessionCategory.admin),
        ]

        entries, bundle = group(blocks)

        assert all(len(categories_of(entry, bundle)) == 1 for entry in entries)

    def test_a_meeting_never_merges_into_other_work(self):
        topic = ("branch", "feature/sso")
        blocks = [
            make_block(minutes=180, topic=topic, category=SessionCategory.coding),
            make_block(start_hour=13, minutes=20, topic=topic, category=SessionCategory.meeting),
        ]

        entries, bundle = group(blocks)

        assert all(len(categories_of(entry, bundle)) == 1 for entry in entries)


class TestSessionBoundedMerging:
    def test_two_topics_in_one_sitting_become_one_entry(self):
        blocks = [
            make_block(minutes=60, topic=("files", "a.py")),
            make_block(start_hour=10, start_minute=10, minutes=60, topic=("files", "b.py")),
        ]

        entries, _ = group(blocks)

        assert len(entries) == 1
        assert entries[0].total_minutes == 120

    def test_a_session_break_keeps_the_work_separate(self):
        blocks = [
            make_block(minutes=60, topic=("files", "a.py")),
            make_block(start_hour=12, minutes=60, topic=("files", "b.py")),
        ]

        entries, _ = group(blocks)

        assert len(entries) == 2

    def test_different_categories_never_merge(self):
        blocks = [
            make_block(minutes=60, topic=("files", "a.py"), category=SessionCategory.coding),
            make_block(start_hour=10, start_minute=5, minutes=60, topic=("files", "b.py"),
                       category=SessionCategory.comms),
        ]

        entries, bundle = group(blocks)

        assert all(len(categories_of(entry, bundle)) == 1 for entry in entries)

    def test_different_projects_never_merge(self):
        blocks = [
            make_block(project="one", minutes=60, topic=("files", "a.py")),
            make_block(project="two", start_hour=10, start_minute=5, minutes=60, topic=("files", "b.py")),
        ]

        entries, _ = group(blocks)

        assert len(entries) == 2

    def test_short_gaps_cannot_chain_past_the_span_cap(self):
        blocks = [
            make_block(start_hour=9, start_minute=90 * index, minutes=60, topic=("files", f"f{index}.py"))
            for index in range(6)
        ]

        entries, bundle = group(blocks)

        for entry in entries:
            spans = [bundle.blocks_by_id[block_id] for block_id in entry.block_ids]
            span = max(b.end_time for b in spans) - min(b.start_time for b in spans)
            assert span.total_seconds() / 60 <= ENTRY_MERGE_MAX_SPAN_MINUTES

    def test_meetings_never_participate(self):
        blocks = [
            make_block(minutes=60, topic=("files", "a.py"), category=SessionCategory.meeting),
            make_block(start_hour=10, start_minute=5, minutes=60, topic=("files", "b.py"),
                       category=SessionCategory.meeting),
        ]

        entries, _ = group(blocks)

        assert len(entries) == 2

    def test_merging_preserves_every_measured_minute(self):
        blocks = [
            make_block(minutes=25, topic=("files", "a.py")),
            make_block(start_hour=9, start_minute=30, minutes=25, topic=("files", "b.py")),
            make_block(start_hour=14, minutes=25, topic=("files", "c.py")),
        ]

        entries, _ = group(blocks)

        assert sum(entry.total_minutes for entry in entries) == 75

    def test_the_result_does_not_depend_on_input_order(self):
        blocks = [
            make_block(start_hour=9, start_minute=70 * index, minutes=40, topic=("files", f"f{index}.py"))
            for index in range(5)
        ]
        bundle = build_evidence([], blocks, [])
        entries = form_entries(bundle)

        forward = [entry.block_ids for entry in merge_adjacent_entries(entries, bundle)]
        reverse = [entry.block_ids for entry in merge_adjacent_entries(list(reversed(entries)), bundle)]

        assert forward == reverse
