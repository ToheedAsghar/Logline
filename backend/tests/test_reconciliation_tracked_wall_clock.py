"""Test that tracked wall-clock minutes count concurrent block time once."""

from datetime import datetime, timedelta, timezone

from app.agent.reconciliation.evidence import compute_tracked_wall_clock_minutes
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory


def _block(start_minute: int, end_minute: int, category=SessionCategory.coding) -> LocalActivityBlock:
    base = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
    start = base + timedelta(minutes=start_minute)
    end = base + timedelta(minutes=end_minute)
    return LocalActivityBlock(
        project="/Users/test/projects/logline",
        start_time=start,
        end_time=end,
        duration=end - start,
        apps=["Code"],
        category=category,
    )


def _by_id(*blocks) -> list[LocalActivityBlock]:
    return list(blocks)


class TestNonOverlappingBlocks:
    def test_a_single_block_is_its_own_duration(self):
        assert compute_tracked_wall_clock_minutes(_by_id(_block(0, 60))) == 60

    def test_disjoint_blocks_sum(self):
        assert compute_tracked_wall_clock_minutes(_by_id(_block(0, 30), _block(60, 90))) == 60

    def test_blocks_touching_end_to_start_sum_without_gap(self):
        assert compute_tracked_wall_clock_minutes(_by_id(_block(0, 30), _block(30, 60))) == 60

    def test_no_blocks_is_zero(self):
        assert compute_tracked_wall_clock_minutes([]) == 0

    def test_tracked_never_exceeds_the_summed_duration_of_measured_blocks(self):
        """Guards the trap that a bundle's merged cluster blocks span their fragments' gaps: for measured blocks
        the union can never exceed the plain sum, so a larger result means non-measured span crept in."""
        blocks = _by_id(_block(0, 30), _block(45, 60), _block(20, 50))
        summed = sum(round(b.duration.total_seconds() / 60) for b in blocks)

        assert compute_tracked_wall_clock_minutes(blocks) <= summed


class TestOverlappingBlocksCountOnce:
    def test_fully_concurrent_blocks_count_once(self):
        """The double-counting bug: a meeting and a non-meeting block covering the same wall-clock time."""
        blocks = _by_id(_block(0, 60), _block(0, 60, category=SessionCategory.meeting))

        assert compute_tracked_wall_clock_minutes(blocks) == 60

    def test_partially_overlapping_blocks_count_the_union(self):
        blocks = _by_id(_block(0, 60), _block(30, 90, category=SessionCategory.meeting))

        assert compute_tracked_wall_clock_minutes(blocks) == 90

    def test_a_block_wholly_inside_another_adds_nothing(self):
        blocks = _by_id(_block(0, 120), _block(30, 60, category=SessionCategory.meeting))

        assert compute_tracked_wall_clock_minutes(blocks) == 120

    def test_tracked_is_less_than_the_naive_sum_when_blocks_overlap(self):
        blocks = _by_id(_block(0, 60), _block(30, 90, category=SessionCategory.meeting))
        naive_sum = sum(round(b.duration.total_seconds() / 60) for b in blocks)

        assert compute_tracked_wall_clock_minutes(blocks) < naive_sum

    def test_three_way_overlap_still_counts_the_union_once(self):
        blocks = _by_id(_block(0, 60), _block(10, 70), _block(20, 80))

        assert compute_tracked_wall_clock_minutes(blocks) == 80

    def test_a_gap_between_merged_runs_is_not_absorbed(self):
        blocks = _by_id(_block(0, 30), _block(15, 45), _block(90, 120))

        assert compute_tracked_wall_clock_minutes(blocks) == 75

    def test_input_order_does_not_change_the_result(self):
        ascending = _by_id(_block(0, 30), _block(15, 45), _block(90, 120))
        descending = _by_id(_block(90, 120), _block(15, 45), _block(0, 30))

        assert compute_tracked_wall_clock_minutes(ascending) == compute_tracked_wall_clock_minutes(descending)
