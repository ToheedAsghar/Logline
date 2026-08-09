"""Test fragment-cluster detection and merging during reconciliation evidence assembly."""

from datetime import datetime, timedelta, timezone

from app.agent.reconciliation.evidence import (
    FRAGMENT_CLUSTER_MAX_SPAN_MINUTES, FRAGMENT_CLUSTER_MIN_BLOCKS, build_evidence, compute_fragment_clusters,
    render_entry_evidence,
)
from app.local_activity.aggregation import LocalActivityBlock, TitleCluster
from app.local_activity.classification import SessionCategory
from app.local_activity.constants import MERGE_GAP_THRESHOLD_MINUTES
from app.matching.matcher import MatchedGroup

UTC = timezone.utc


def make_block(
    start,
    minutes,
    project=None,
    category=SessionCategory.admin,
    apps=None,
    deterministic_topic=None,
    title_digest=None,
):
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration,
        apps=apps if apps is not None else ["Firefox"], category=category,
        deterministic_topic=deterministic_topic,
        title_digest=[] if title_digest is None else title_digest,
    )


def _t(minute_offset):
    return datetime(2026, 8, 6, 9, 0, tzinfo=UTC) + timedelta(minutes=minute_offset)


def render_all(bundle):
    """Render every chargeable block in one text, the way a single entry's evidence is rendered."""
    return render_entry_evidence(list(bundle.blocks_by_id), bundle)


class TestComputeFragmentClustersDirectly:
    def test_three_adjacent_project_less_blocks_form_one_cluster(self):
        blocks_by_id = {
            1: make_block(_t(0), 2),
            2: make_block(_t(2), 1, category=SessionCategory.comms),
            3: make_block(_t(3), 3, category=SessionCategory.code_review),
        }

        clusters = compute_fragment_clusters(blocks_by_id)

        assert len(clusters) == 1
        assert clusters[0].block_ids == [1, 2, 3]
        assert clusters[0].span_minutes == 6

    def test_two_blocks_do_not_form_a_cluster(self):
        blocks_by_id = {1: make_block(_t(0), 2), 2: make_block(_t(2), 1)}

        assert compute_fragment_clusters(blocks_by_id) == []

    def test_fewer_than_min_blocks_below_threshold_never_clusters(self):
        blocks_by_id = {i: make_block(_t(i * 2), 1) for i in range(FRAGMENT_CLUSTER_MIN_BLOCKS - 1)}

        assert compute_fragment_clusters(blocks_by_id) == []

    def test_a_gap_at_or_over_the_merge_threshold_splits_the_run(self):
        blocks_by_id = {
            1: make_block(_t(0), 1),
            2: make_block(_t(1), 1),
            3: make_block(_t(2 + MERGE_GAP_THRESHOLD_MINUTES), 1),
            4: make_block(_t(3 + MERGE_GAP_THRESHOLD_MINUTES), 1),
        }

        clusters = compute_fragment_clusters(blocks_by_id)

        assert clusters == []

    def test_a_block_with_a_project_breaks_the_run_and_is_never_a_cluster_member(self):
        blocks_by_id = {
            1: make_block(_t(0), 1),
            2: make_block(_t(1), 1),
            3: make_block(_t(2), 1),
            4: make_block(_t(3), 1, project="logline", category=SessionCategory.coding),
            5: make_block(_t(4), 1),
            6: make_block(_t(5), 1),
            7: make_block(_t(6), 1),
        }

        clusters = compute_fragment_clusters(blocks_by_id)

        assert len(clusters) == 2
        assert clusters[0].block_ids == [1, 2, 3]
        assert clusters[1].block_ids == [5, 6, 7]
        assert all(4 not in cluster.block_ids for cluster in clusters)

    def test_a_meeting_block_breaks_the_run_even_though_its_project_is_none(self):
        """Meeting blocks always have project=None (aggregation forces this) but must never join a cluster -- rules 6-7
        always take priority and a cluster hint must never suggest folding a meeting in."""
        blocks_by_id = {
            1: make_block(_t(0), 1),
            2: make_block(_t(1), 1),
            3: make_block(_t(2), 8, category=SessionCategory.meeting),
            4: make_block(_t(10), 1),
            5: make_block(_t(11), 1),
        }

        clusters = compute_fragment_clusters(blocks_by_id)

        assert clusters == []

    def test_span_cap_splits_a_long_run_into_multiple_clusters(self):
        step = 6
        blocks_by_id = {i: make_block(_t(i * step), 1) for i in range(10)}

        clusters = compute_fragment_clusters(blocks_by_id)

        assert len(clusters) == 2
        assert clusters[0].block_ids == [0, 1, 2, 3, 4]
        assert clusters[1].block_ids == [5, 6, 7, 8, 9]
        for cluster in clusters:
            assert cluster.span_minutes <= FRAGMENT_CLUSTER_MAX_SPAN_MINUTES
            assert len(cluster.block_ids) >= FRAGMENT_CLUSTER_MIN_BLOCKS

    def test_clustering_is_independent_of_dict_iteration_order_using_real_chronology(self):
        blocks_by_id = {
            3: make_block(_t(4), 1),
            1: make_block(_t(0), 1),
            2: make_block(_t(2), 1),
        }

        clusters = compute_fragment_clusters(blocks_by_id)

        assert len(clusters) == 1
        assert clusters[0].block_ids == [1, 2, 3]

    def test_two_distinct_nonempty_topics_split_a_fragment_run(self):
        blocks_by_id = {
            1: make_block(_t(0), 1, deterministic_topic=("pr", "20")),
            2: make_block(_t(1), 1),
            3: make_block(_t(2), 1, deterministic_topic=("pr", "48")),
            4: make_block(_t(3), 1),
        }

        assert compute_fragment_clusters(blocks_by_id) == []


class TestFragmentClusterRendering:
    """build_evidence merges cluster-eligible blocks into one block.

    There's no rule for the model to apply and no way to opt out -- merging always happens once eligibility criteria are
    met (>=3 blocks, gaps <15min, span <=30min).
    """

    def test_cluster_eligible_blocks_merge_into_a_single_block(self):
        blocks = [make_block(_t(0), 2), make_block(_t(2), 1), make_block(_t(3), 3)]

        bundle = build_evidence([], blocks, [])

        assert len(bundle.blocks_by_id) == 1
        assert "block 1 |" in render_all(bundle)
        assert "block 2 |" not in render_all(bundle)
        assert "block 3 |" not in render_all(bundle)

    def test_merged_minutes_equal_the_sum_of_each_members_own_measured_duration_exactly(self):
        blocks = [make_block(_t(0), 3), make_block(_t(3), 1), make_block(_t(4), 5)]

        bundle = build_evidence([], blocks, [])

        assert bundle.blocks_by_id[1].duration == timedelta(minutes=9)
        assert "9 min measured" in render_all(bundle)

    def test_merge_is_unconditional_when_criteria_are_met(self):
        blocks = [
            make_block(_t(0), 2, category=SessionCategory.admin),
            make_block(_t(2), 1, category=SessionCategory.comms),
            make_block(_t(3), 3, category=SessionCategory.code_review),
        ]

        bundle = build_evidence([], blocks, [])

        assert len(bundle.blocks_by_id) == 1

    def test_merged_block_category_is_whichever_member_holds_the_most_duration(self):
        blocks = [
            make_block(_t(0), 1, category=SessionCategory.admin),
            make_block(_t(1), 1, category=SessionCategory.comms),
            make_block(_t(2), 5, category=SessionCategory.code_review),
        ]

        bundle = build_evidence([], blocks, [])

        assert bundle.blocks_by_id[1].category == SessionCategory.code_review

    def test_merged_block_category_ties_break_by_first_chronological_occurrence(self):
        blocks = [
            make_block(_t(0), 3, category=SessionCategory.admin),
            make_block(_t(3), 3, category=SessionCategory.comms),
            make_block(_t(6), 3, category=SessionCategory.code_review),
        ]

        bundle = build_evidence([], blocks, [])

        assert bundle.blocks_by_id[1].category == SessionCategory.admin

    def test_pr_topic_is_not_promoted_when_a_non_review_category_wins(self):
        pr_title = "FIX(tracker): ignore self process · Pull Request #48 · ToheedAsghar/Logline"
        blocks = [
            make_block(_t(0), 5, category=SessionCategory.admin),
            make_block(
                _t(5),
                1,
                category=SessionCategory.code_review,
                deterministic_topic=("pr", "48"),
                title_digest=[TitleCluster(title=pr_title, seconds=60)],
            ),
            make_block(_t(6), 2, category=SessionCategory.admin),
        ]

        bundle = build_evidence([], blocks, [])

        merged = bundle.blocks_by_id[1]
        assert merged.category == SessionCategory.admin
        assert merged.deterministic_topic is None
        assert any("Pull Request #48" in cluster.title for cluster in merged.title_digest)

    def test_pr_topic_is_promoted_when_code_review_wins(self):
        blocks = [
            make_block(
                _t(0),
                5,
                category=SessionCategory.code_review,
                deterministic_topic=("pr", "48"),
            ),
            make_block(_t(5), 1, category=SessionCategory.admin),
            make_block(_t(6), 1, category=SessionCategory.comms),
        ]

        bundle = build_evidence([], blocks, [])

        assert bundle.blocks_by_id[1].category == SessionCategory.code_review
        assert bundle.blocks_by_id[1].deterministic_topic == ("pr", "48")

    def test_branch_topic_still_propagates_when_another_category_wins(self):
        blocks = [
            make_block(_t(0), 5, category=SessionCategory.admin),
            make_block(
                _t(5),
                1,
                category=SessionCategory.coding,
                deterministic_topic=("branch", "feature/sso"),
            ),
            make_block(_t(6), 2, category=SessionCategory.admin),
        ]

        bundle = build_evidence([], blocks, [])

        assert bundle.blocks_by_id[1].category == SessionCategory.admin
        assert bundle.blocks_by_id[1].deterministic_topic == ("branch", "feature/sso")

    def test_merged_block_apps_are_unioned_in_first_seen_chronological_order(self):
        blocks = [
            make_block(_t(0), 1, apps=["Slack"]),
            make_block(_t(1), 1, apps=["Firefox", "Slack"]),
            make_block(_t(2), 1, apps=["Terminal"]),
        ]

        bundle = build_evidence([], blocks, [])

        assert bundle.blocks_by_id[1].apps == ["Slack", "Firefox", "Terminal"]

    def test_no_merge_for_fewer_than_three_project_less_blocks(self):
        blocks = [make_block(_t(0), 2), make_block(_t(2), 1)]

        bundle = build_evidence([], blocks, [])

        assert len(bundle.blocks_by_id) == 2
        assert bundle.blocks_by_id[1].duration == timedelta(minutes=2)
        assert bundle.blocks_by_id[2].duration == timedelta(minutes=1)

    def test_no_merge_for_blocks_with_a_project(self):
        blocks = [
            make_block(_t(0), 2, project="logline", category=SessionCategory.coding),
            make_block(_t(2), 1, project="logline", category=SessionCategory.coding),
            make_block(_t(3), 3, project="logline", category=SessionCategory.coding),
        ]

        bundle = build_evidence([], blocks, [])

        assert len(bundle.blocks_by_id) == 3

    def test_merge_position_when_a_member_is_matched(self):
        """In real usage a cluster-eligible block is never matched (matching needs a project, and cluster blocks never
        have one), but `build_evidence` doesn't enforce that -- this constructs the case directly to check merging still
        works if it ever happens."""
        late_matched = make_block(_t(10), 1)
        early_unmatched = make_block(_t(0), 1)
        mid_unmatched = make_block(_t(5), 1)

        bundle = build_evidence(
            [MatchedGroup(block=late_matched, events=[])], [early_unmatched, mid_unmatched], []
        )

        assert len(bundle.blocks_by_id) == 1
        assert bundle.blocks_by_id[1].duration == timedelta(minutes=3)

    def test_sub_minute_members_cluster_before_zero_minute_filtering(self):
        blocks = [
            make_block(
                _t(0) + timedelta(seconds=20 * index),
                1 / 3,
                title_digest=[TitleCluster(title="PR #45", seconds=20)],
            )
            for index in range(3)
        ]

        bundle = build_evidence([], blocks, [])

        assert len(bundle.blocks_by_id) == 1
        assert bundle.blocks_by_id[1].duration == timedelta(minutes=1)
        assert 'title | 1 min | "PR #45"' in render_all(bundle)
