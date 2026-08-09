"""Test deterministic work-log entry formation from reconciliation evidence."""

from datetime import datetime, timedelta, timezone

from app.agent.reconciliation.entries import CATEGORY_TO_TAG, form_entries
from app.agent.reconciliation.evidence import build_evidence
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory
from app.matching.matcher import MatchedGroup, RemoteEventData

UTC = timezone.utc


def make_block(
    project="logline",
    start_hour=9,
    start_minute=0,
    minutes=90,
    category=SessionCategory.coding,
    apps=None,
    deterministic_topic=None,
):
    start = datetime(2026, 8, 6, start_hour, start_minute, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration,
        apps=apps if apps is not None else ["vscode"], category=category,
        deterministic_topic=deterministic_topic,
    )


def make_event(external_id="gh:pr:41", source="github", occurred_hour=9, occurred_minute=30, summary="PR"):
    return RemoteEventData(
        external_id=external_id, source=source, remote_project_id="logline",
        occurred_at=datetime(2026, 8, 6, occurred_hour, occurred_minute, tzinfo=UTC),
        event_type="pull_request", summary=summary,
    )


class TestMeetingBlocksAlwaysGetTheirOwnEntry:
    def test_two_meeting_blocks_never_merge_even_with_the_same_project_and_category(self):
        first = make_block(project=None, start_hour=9, minutes=15, category=SessionCategory.meeting)
        second = make_block(project=None, start_hour=9, start_minute=15, minutes=15, category=SessionCategory.meeting)
        bundle = build_evidence([], [first, second], [])

        entries = form_entries(bundle)

        assert len(entries) == 2
        assert all(entry.category == SessionCategory.meeting for entry in entries)
        assert all(len(entry.block_ids) == 1 for entry in entries)


class TestNonMeetingGrouping:
    def test_same_date_project_category_blocks_merge_into_one_entry(self):
        morning = make_block(project="logline", category=SessionCategory.coding, start_hour=9, minutes=30)
        afternoon = make_block(project="logline", category=SessionCategory.coding, start_hour=14, minutes=45)
        bundle = build_evidence([], [morning, afternoon], [])

        entries = form_entries(bundle)

        assert len(entries) == 1
        assert entries[0].total_minutes == 75
        assert len(entries[0].allocations) == 2

    def test_different_projects_never_merge(self):
        logline = make_block(project="logline", category=SessionCategory.coding, start_hour=9, minutes=30)
        other = make_block(project="other-repo", category=SessionCategory.coding, start_hour=10, minutes=30)
        bundle = build_evidence([], [logline, other], [])

        assert len(form_entries(bundle)) == 2

    def test_different_categories_never_merge(self):
        coding = make_block(project="logline", category=SessionCategory.coding, start_hour=9, minutes=30)
        review = make_block(project="logline", category=SessionCategory.code_review, start_hour=10, minutes=30)
        bundle = build_evidence([], [coding, review], [])

        assert len(form_entries(bundle)) == 2

    def test_different_dates_never_merge(self):
        day_one = make_block(project="logline", category=SessionCategory.coding, start_hour=9, minutes=30)
        start = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
        day_two = LocalActivityBlock(
            project="logline", start_time=start, end_time=start + timedelta(minutes=30),
            duration=timedelta(minutes=30), apps=["vscode"], category=SessionCategory.coding,
        )
        bundle = build_evidence([], [day_one, day_two], [])

        assert len(form_entries(bundle)) == 2

    def test_project_less_blocks_group_by_category_alone(self):
        morning = make_block(project=None, category=SessionCategory.admin, start_hour=9, minutes=5)
        afternoon = make_block(project=None, category=SessionCategory.admin, start_hour=14, minutes=10)
        bundle = build_evidence([], [morning, afternoon], [])

        entries = form_entries(bundle)

        assert len(entries) == 1
        assert entries[0].project is None

    def test_different_deterministic_topics_never_merge(self):
        sso = make_block(
            project="logline",
            category=SessionCategory.coding,
            start_hour=9,
            minutes=30,
            deterministic_topic=("branch", "feature/sso"),
        )
        settings = make_block(
            project="logline",
            category=SessionCategory.coding,
            start_hour=10,
            minutes=30,
            deterministic_topic=("branch", "feature/settings-ui"),
        )
        bundle = build_evidence([], [sso, settings], [])

        entries = form_entries(bundle)

        assert len(entries) == 2

    def test_same_exact_deterministic_topic_still_groups(self):
        morning = make_block(
            project="logline",
            category=SessionCategory.coding,
            start_hour=9,
            minutes=30,
            deterministic_topic=("branch", "feature/sso"),
        )
        afternoon = make_block(
            project="logline",
            category=SessionCategory.coding,
            start_hour=14,
            minutes=45,
            deterministic_topic=("branch", "feature/sso"),
        )
        bundle = build_evidence([], [morning, afternoon], [])

        entries = form_entries(bundle)

        assert len(entries) == 1
        assert entries[0].total_minutes == 75

    def test_block_ids_within_a_group_are_chronologically_ordered_regardless_of_input_order(self):
        early = make_block(project="logline", category=SessionCategory.coding, start_hour=8, minutes=10)
        late = make_block(project="logline", category=SessionCategory.coding, start_hour=16, minutes=10)
        bundle = build_evidence([], [late, early], [])

        entries = form_entries(bundle)

        starts = [bundle.blocks_by_id[block_id].start_time for block_id in entries[0].block_ids]
        assert starts == sorted(starts)


class TestTopicFloor:
    def test_under_ten_minute_pr_candidate_merges_into_the_topicless_entry(self):
        first_review = make_block(
            start_hour=9,
            minutes=4,
            category=SessionCategory.code_review,
            deterministic_topic=("pr", "48"),
        )
        second_review = make_block(
            start_hour=10,
            minutes=5,
            category=SessionCategory.code_review,
            deterministic_topic=("pr", "48"),
        )
        topicless = make_block(
            start_hour=11,
            minutes=20,
            category=SessionCategory.code_review,
        )
        event = make_event(external_id="logline#48")
        bundle = build_evidence(
            [
                MatchedGroup(block=first_review, events=[event]),
                MatchedGroup(block=second_review, events=[event]),
            ],
            [topicless],
            [],
        )

        entries = form_entries(bundle)

        assert len(entries) == 1
        assert entries[0].total_minutes == 29
        assert entries[0].source_remote_event_ids == ["logline#48"]
        assert sorted(entries[0].block_ids) == sorted(bundle.blocks_by_id)
        assert bundle.blocks_by_id[1].deterministic_topic == ("pr", "48")

    def test_exactly_ten_minute_pr_candidate_keeps_its_own_entry(self):
        review = make_block(
            start_hour=9,
            minutes=10,
            category=SessionCategory.code_review,
            deterministic_topic=("pr", "48"),
        )
        topicless = make_block(
            start_hour=11,
            minutes=20,
            category=SessionCategory.code_review,
        )
        bundle = build_evidence([], [review, topicless], [])

        entries = form_entries(bundle)

        assert len(entries) == 2
        assert sorted(entry.total_minutes for entry in entries) == [10, 20]

    def test_floor_uses_the_whole_branch_candidate_not_individual_blocks(self):
        morning = make_block(
            start_hour=9,
            minutes=6,
            deterministic_topic=("branch", "feature/sso"),
        )
        afternoon = make_block(
            start_hour=14,
            minutes=6,
            deterministic_topic=("branch", "feature/sso"),
        )
        topicless = make_block(start_hour=16, minutes=20)
        bundle = build_evidence([], [morning, afternoon, topicless], [])

        entries = form_entries(bundle)

        assert len(entries) == 2
        assert sorted(entry.total_minutes for entry in entries) == [12, 20]

    def test_under_ten_minute_project_name_candidate_keeps_its_own_entry(self):
        named = make_block(
            start_hour=9,
            minutes=1,
            deterministic_topic=("project_name", "time-log-helper"),
        )
        topicless = make_block(start_hour=10, minutes=20)
        bundle = build_evidence([], [named, topicless], [])

        entries = form_entries(bundle)

        assert len(entries) == 2

    def test_floor_never_merges_different_categories(self):
        review = make_block(
            start_hour=9,
            minutes=1,
            category=SessionCategory.code_review,
            deterministic_topic=("pr", "48"),
        )
        admin = make_block(
            start_hour=10,
            minutes=20,
            category=SessionCategory.admin,
        )
        bundle = build_evidence([], [review, admin], [])

        entries = form_entries(bundle)

        assert len(entries) == 2
        assert {entry.category for entry in entries} == {
            SessionCategory.admin,
            SessionCategory.code_review,
        }


class TestBaseTagMapping:
    def test_every_category_maps_to_its_expected_tag(self):
        for category, expected_tag in CATEGORY_TO_TAG.items():
            project = None if category == SessionCategory.meeting else "logline"
            bundle = build_evidence([], [make_block(project=project, category=category, minutes=30)], [])

            assert form_entries(bundle)[0].base_tag == expected_tag


class TestSourceRemoteEventIds:
    def test_events_from_every_member_block_are_unioned(self):
        morning = make_block(project="logline", category=SessionCategory.coding, start_hour=9, minutes=30)
        afternoon = make_block(project="logline", category=SessionCategory.coding, start_hour=14, minutes=30)
        morning_event = make_event(external_id="gh:pr:1", occurred_hour=9, occurred_minute=15)
        afternoon_event = make_event(external_id="gh:pr:2", occurred_hour=14, occurred_minute=15)
        bundle = build_evidence(
            [
                MatchedGroup(block=morning, events=[morning_event]),
                MatchedGroup(block=afternoon, events=[afternoon_event]),
            ],
            [],
            [],
        )

        entries = form_entries(bundle)

        assert set(entries[0].source_remote_event_ids) == {"gh:pr:1", "gh:pr:2"}


class TestOverlapReviewReason:
    def test_a_non_meeting_entry_overlapping_a_meeting_gets_a_review_reason(self):
        meeting = make_block(project=None, category=SessionCategory.meeting, start_hour=9, minutes=60)
        coding = make_block(
            project="logline", category=SessionCategory.coding, start_hour=9, start_minute=15, minutes=20
        )
        bundle = build_evidence([], [meeting, coding], [])

        entries = form_entries(bundle)

        coding_entry = next(entry for entry in entries if entry.category == SessionCategory.coding)
        assert coding_entry.review_reason is not None
        assert "Meeting" in coding_entry.review_reason

    def test_no_review_reason_when_nothing_overlaps(self):
        bundle = build_evidence([], [make_block(project="logline", category=SessionCategory.coding, minutes=30)], [])

        assert form_entries(bundle)[0].review_reason is None


class TestOrdering:
    def test_entries_are_sorted_by_descending_total_minutes(self):
        small = make_block(project="a", category=SessionCategory.coding, start_hour=9, minutes=10)
        big = make_block(project="b", category=SessionCategory.coding, start_hour=10, minutes=90)
        bundle = build_evidence([], [small, big], [])

        entries = form_entries(bundle)

        assert [entry.total_minutes for entry in entries] == [90, 10]


class TestEveryBlockIsAssignedToExactlyOneEntry:
    def test_no_block_is_left_out_or_duplicated_across_entries(self):
        coding = make_block(project="logline", category=SessionCategory.coding, start_hour=9, minutes=30)
        admin = make_block(project=None, category=SessionCategory.admin, start_hour=14, minutes=5)
        bundle = build_evidence([], [coding, admin], [])

        entries = form_entries(bundle)

        all_ids = [block_id for entry in entries for block_id in entry.block_ids]
        assert sorted(all_ids) == sorted(bundle.blocks_by_id)
        assert len(all_ids) == len(set(all_ids))

    def test_empty_bundle_yields_no_entries(self):
        assert form_entries(build_evidence([], [], [])) == []
