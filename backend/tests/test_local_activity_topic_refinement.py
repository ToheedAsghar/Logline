"""Test post-aggregation refinement of coarse block topics into per-strand topics."""

from datetime import datetime, timedelta, timezone

from app.local_activity.aggregation import LocalActivityBlock, TitleCluster
from app.local_activity.classification import SessionCategory
from app.local_activity.constants import MAX_TOPIC_STRAND_MINUTES
from app.local_activity.topic_refinement import normalize_file_name, refine_block_topics, refine_blocks_by_id

UTC = timezone.utc


def make_block(
    start_hour=9,
    start_minute=0,
    minutes=30,
    titles=(),
    category=SessionCategory.coding,
    topic=None,
    meeting_name=None,
    project=None,
):
    start = datetime(2026, 8, 6, start_hour, 0, tzinfo=UTC) + timedelta(minutes=start_minute)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project,
        start_time=start,
        end_time=start + duration,
        duration=duration,
        apps=["Code"],
        category=category,
        title_digest=[TitleCluster(title=title, seconds=seconds) for title, seconds in titles],
        deterministic_topic=topic,
        meeting_name=meeting_name,
    )


class TestTopicsThatMustNotChange:
    def test_a_pr_topic_is_left_alone(self):
        block = make_block(titles=[("routers.py — logline", 600)], topic=("pr", "36"))

        assert refine_block_topics([block])[0].deterministic_topic == ("pr", "36")

    def test_a_branch_topic_is_left_alone(self):
        block = make_block(titles=[("routers.py — logline", 600)], topic=("branch", "toheed/feature/sso"))

        assert refine_block_topics([block])[0].deterministic_topic == ("branch", "toheed/feature/sso")

    def test_a_meeting_block_is_left_alone(self):
        block = make_block(category=SessionCategory.meeting, meeting_name="Daily Standup", titles=[("Meet", 60)])

        assert refine_block_topics([block])[0].deterministic_topic is None

    def test_input_order_is_preserved_so_callers_can_zip_ids_back(self):
        late = make_block(start_hour=15, titles=[("a.py — x", 60)])
        early = make_block(start_hour=9, titles=[("b.py — x", 60)])

        refined = refine_block_topics([late, early])

        assert [block.start_time for block in refined] == [late.start_time, early.start_time]

    def test_refining_by_id_keeps_every_block_id(self):
        blocks_by_id = {7: make_block(start_hour=9, titles=[("a.py — x", 60)]), 3: make_block(start_hour=15)}

        refined = refine_blocks_by_id(blocks_by_id)

        assert set(refined) == {7, 3}
        assert refined[7].start_time == blocks_by_id[7].start_time

    def test_measured_durations_are_never_changed(self):
        blocks = [make_block(start_hour=9, minutes=30), make_block(start_hour=10, minutes=45)]

        refined = refine_block_topics(blocks)

        assert [block.duration for block in refined] == [timedelta(minutes=30), timedelta(minutes=45)]


class TestFileClusterTopics:
    def test_a_topicless_block_gains_a_topic_from_its_dominant_files(self):
        block = make_block(titles=[("prompt.py — logline", 600), ("system_prompt.py — logline", 400)])

        kind, value = refine_block_topics([block])[0].deterministic_topic

        assert kind == "files"
        assert "prompt.py" in value

    def test_a_project_wide_topic_is_refined_by_files(self):
        block = make_block(titles=[("prompt.py — logline", 600)], topic=("project_name", "logline"))

        kind, value = refine_block_topics([block])[0].deterministic_topic

        assert kind == "files"
        assert value.startswith("logline:")

    def test_consecutive_blocks_sharing_a_file_get_the_same_topic(self):
        first = make_block(start_hour=9, titles=[("prompt.py — logline", 600)])
        second = make_block(start_hour=9, start_minute=35, titles=[("prompt.py — logline", 300)])

        refined = refine_block_topics([first, second])

        assert refined[0].deterministic_topic == refined[1].deterministic_topic

    def test_blocks_touching_unrelated_files_get_different_topics(self):
        first = make_block(start_hour=9, titles=[("prompt.py — logline", 600)])
        second = make_block(start_hour=9, start_minute=35, titles=[("routers.py — logline", 600)])

        refined = refine_block_topics([first, second])

        assert refined[0].deterministic_topic != refined[1].deterministic_topic

    def test_work_never_crosses_a_project_scope(self):
        first = make_block(start_hour=9, titles=[("shared.py — x", 600)], topic=("project_name", "logline"))
        second = make_block(
            start_hour=9, start_minute=35, titles=[("shared.py — x", 600)], topic=("project_name", "logline-recon")
        )

        refined = refine_block_topics([first, second])

        assert refined[0].deterministic_topic != refined[1].deterministic_topic


class TestOverlapIsMeasuredAgainstDominantFiles:
    def test_one_shared_file_does_not_chain_unrelated_work_together(self):
        """Matching the accumulated union instead would let a file common to both ends merge the whole run."""
        first = make_block(start_hour=9, titles=[("prompt.py — logline", 3000)])
        bridge = make_block(start_hour=9, start_minute=55, titles=[("prompt.py — logline", 60), ("api.py — l", 3000)])
        last = make_block(start_hour=10, start_minute=50, titles=[("api.py — l", 60), ("tracker.py — l", 3000)])

        refined = refine_block_topics([first, bridge, last])

        assert refined[0].deterministic_topic != refined[2].deterministic_topic


class TestBoundedInheritance:
    def test_a_file_less_block_inherits_a_nearby_strand(self):
        anchor = make_block(start_hour=9, titles=[("prompt.py — logline", 600)])
        quiet = make_block(start_hour=9, start_minute=35, titles=[("Terminal", 300)])

        refined = refine_block_topics([anchor, quiet])

        assert refined[1].deterministic_topic == refined[0].deterministic_topic

    def test_a_file_less_block_beyond_the_window_does_not_inherit(self):
        anchor = make_block(start_hour=9, minutes=10, titles=[("prompt.py — logline", 600)])
        distant = make_block(start_hour=9, start_minute=40, titles=[("Terminal", 300)])

        refined = refine_block_topics([anchor, distant])

        assert refined[1].deterministic_topic != refined[0].deterministic_topic

    def test_a_block_with_no_files_at_all_gets_a_general_topic(self):
        block = make_block(titles=[("Terminal", 300)])

        assert refine_block_topics([block])[0].deterministic_topic[0] == "general"


class TestSessionGaps:
    def test_a_session_gap_starts_a_new_general_entry(self):
        first = make_block(start_hour=9, minutes=30, titles=[("Terminal", 300)])
        second = make_block(start_hour=11, minutes=30, titles=[("Terminal", 300)])

        refined = refine_block_topics([first, second])

        assert refined[0].deterministic_topic != refined[1].deterministic_topic

    def test_the_same_files_after_a_session_gap_regroup_as_one_topic(self):
        """File-derived work resumed later in the day is the same work, unlike an unidentifiable general stretch."""
        first = make_block(start_hour=9, minutes=30, titles=[("prompt.py — logline", 600)])
        second = make_block(start_hour=13, minutes=30, titles=[("prompt.py — logline", 600)])

        refined = refine_block_topics([first, second])

        assert refined[0].deterministic_topic == refined[1].deterministic_topic


class TestDurationBackstop:
    def test_an_oversized_strand_is_split(self):
        blocks = [
            make_block(start_hour=9, start_minute=step * 40, minutes=35, titles=[("prompt.py — logline", 2100)])
            for step in range(5)
        ]

        refined = refine_block_topics(blocks)

        assert len({block.deterministic_topic for block in refined}) > 1

    def test_every_piece_fits_the_cap(self):
        blocks = [
            make_block(start_hour=9, start_minute=step * 40, minutes=35, titles=[("prompt.py — logline", 2100)])
            for step in range(5)
        ]

        refined = refine_block_topics(blocks)

        minutes_by_topic: dict[tuple[str, str], float] = {}
        for block in refined:
            topic = block.deterministic_topic
            minutes_by_topic[topic] = minutes_by_topic.get(topic, 0) + block.duration.total_seconds() / 60
        assert max(minutes_by_topic.values()) <= MAX_TOPIC_STRAND_MINUTES

    def test_the_cut_lands_on_the_widest_measured_gap(self):
        blocks = [
            make_block(start_hour=9, minutes=60, titles=[("prompt.py — logline", 3600)]),
            make_block(start_hour=10, minutes=60, titles=[("prompt.py — logline", 3600)]),
            make_block(start_hour=11, start_minute=30, minutes=60, titles=[("prompt.py — logline", 3600)]),
        ]

        refined = refine_block_topics(blocks)

        assert refined[0].deterministic_topic == refined[1].deterministic_topic
        assert refined[2].deterministic_topic != refined[1].deterministic_topic


class TestTimestampedFileNames:
    def test_a_rotating_log_name_normalizes_to_one_identity(self):
        assert normalize_file_name("logs_2026-08-03.md") == "logs.md"
        assert normalize_file_name("backup.20260803.sql") == "backup.sql"
        assert normalize_file_name("app-1737.log") == "app.log"
        assert normalize_file_name("report_20260803_1430.csv") == "report.csv"

    def test_an_ordinary_source_name_is_untouched(self):
        assert normalize_file_name("routers.py") == "routers.py"
        assert normalize_file_name("dump_raw_logs.py") == "dump_raw_logs.py"
        assert normalize_file_name("test_remote_fetch_orchestrator.py") == "test_remote_fetch_orchestrator.py"

    def test_a_stem_that_would_empty_is_kept_whole(self):
        assert normalize_file_name("2026-08-03.md") == "2026-08-03.md"

    def test_two_days_of_one_rotating_log_share_a_topic(self):
        blocks = [
            make_block(start_hour=9, titles=[("logs_2026-08-03.md", 600)]),
            make_block(start_hour=9, start_minute=30, titles=[("logs_2026-08-04.md", 600)]),
        ]

        refined = refine_block_topics(blocks)

        assert refined[0].deterministic_topic == refined[1].deterministic_topic
        assert refined[0].deterministic_topic[0] == "files"

    def test_newly_recognised_extensions_produce_a_file_topic(self):
        blocks = [make_block(titles=[("trace.jsonl", 600), ("notes.txt", 600)])]

        refined = refine_block_topics(blocks)

        assert refined[0].deterministic_topic[0] == "files"
