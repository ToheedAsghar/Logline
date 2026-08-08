"""
Tests for aggregate_local_activity (app/local_activity/aggregation.py), the
first step of the Phase 4 local-tracker pipeline: collapsing fragmented raw
tracker rows into one block per continuous stretch of work.

This is pure logic with no I/O, so every case below runs entirely against
in-memory RawSessionRow fixtures -- no database, no real tracker, no LLM.
Coverage follows the two things that must never happen: merging across
projects, and merging across a gap of MERGE_GAP_THRESHOLD_MINUTES or more.
"""

from datetime import datetime, timedelta, timezone

from app.local_activity.aggregation import LocalActivityBlock, RawSessionRow, aggregate_local_activity
from app.local_activity.classification import SessionCategory
from app.local_activity.constants import MERGE_GAP_THRESHOLD_MINUTES, MICRO_IDLE_ABSORB_SECONDS

PROJECT_A = "/Users/dev/projects/logline"
PROJECT_B = "/Users/dev/projects/other-repo"


def _row(
    project: str, app: str, start: datetime, end: datetime, category: SessionCategory = SessionCategory.coding
) -> RawSessionRow:
    return RawSessionRow(project=project, app=app, start_time=start, end_time=end, category=category)


def _at(minute_offset: int) -> datetime:
    """Minutes offset from a fixed anchor, so gaps in test data are legible
    as plain integers instead of repeated datetime(...) literals."""
    return datetime(2026, 7, 24, 9, 0) + timedelta(minutes=minute_offset)


class TestBasicMerging:
    def test_several_same_project_rows_with_small_gaps_merge_into_one_block(self):
        rows = [
            _row(PROJECT_A, "vscode", _at(0), _at(10)),
            _row(PROJECT_A, "terminal", _at(12), _at(20)),
            _row(PROJECT_A, "vscode", _at(22), _at(30)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        block = blocks[0]
        assert block.project == PROJECT_A
        assert block.start_time == _at(0)
        assert block.end_time == _at(30)
        assert block.duration == timedelta(minutes=30)
        assert block.apps == ["vscode", "terminal"]

    def test_single_isolated_row_produces_one_block_with_no_merging(self):
        rows = [_row(PROJECT_A, "vscode", _at(0), _at(5))]

        blocks = aggregate_local_activity(rows)

        assert blocks == [
            LocalActivityBlock(
                project=PROJECT_A,
                start_time=_at(0),
                end_time=_at(5),
                duration=timedelta(minutes=5),
                apps=["vscode"],
                category=SessionCategory.coding,
            )
        ]

    def test_empty_input_returns_empty_list(self):
        assert aggregate_local_activity([]) == []


class TestGapBoundary:
    """'Under 15 minutes' must have one precise, tested meaning: a gap
    strictly less than the threshold merges, a gap of exactly the threshold
    (or more) splits."""

    def test_gap_just_under_threshold_merges(self):
        first_end = _at(0)
        second_start = first_end + timedelta(minutes=MERGE_GAP_THRESHOLD_MINUTES) - timedelta(seconds=1)
        rows = [
            _row(PROJECT_A, "vscode", _at(-10), first_end),
            _row(PROJECT_A, "terminal", second_start, second_start + timedelta(minutes=5)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1

    def test_gap_of_exactly_threshold_minutes_splits(self):
        first_end = _at(0)
        second_start = first_end + timedelta(minutes=MERGE_GAP_THRESHOLD_MINUTES)
        rows = [
            _row(PROJECT_A, "vscode", _at(-10), first_end),
            _row(PROJECT_A, "terminal", second_start, second_start + timedelta(minutes=5)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2
        assert blocks[0].end_time == first_end
        assert blocks[1].start_time == second_start

    def test_gap_of_more_than_threshold_splits(self):
        rows = [
            _row(PROJECT_A, "vscode", _at(0), _at(10)),
            _row(PROJECT_A, "vscode", _at(400), _at(410)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2


class TestProjectIsolation:
    def test_interleaved_different_projects_never_merge_across_each_other(self):
        """Each project's rows here have a small (mergeable-sized) gap to the row's own next occurrence,
        but every one of those gaps is bridged by the *other* project's row sitting in between. A block
        must never span across another project's real, interleaved activity -- so this collapses to one
        block per row (four total), not one merged block per project spanning the other project's time."""
        rows = [
            _row(PROJECT_A, "vscode", _at(0), _at(5)),
            _row(PROJECT_B, "terminal", _at(5), _at(10)),
            _row(PROJECT_A, "vscode", _at(10), _at(15)),
            _row(PROJECT_B, "terminal", _at(15), _at(20)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 4
        assert [(block.project, block.start_time, block.end_time) for block in blocks] == [
            (PROJECT_A, _at(0), _at(5)),
            (PROJECT_B, _at(5), _at(10)),
            (PROJECT_A, _at(10), _at(15)),
            (PROJECT_B, _at(15), _at(20)),
        ]

    def test_same_project_rows_with_no_interleaving_still_merge_normally(self):
        """Contrast with the above: when nothing else sits between two same-key rows, the ordinary gap
        rule still applies and they merge into one block."""
        rows = [
            _row(PROJECT_A, "vscode", _at(0), _at(5)),
            _row(PROJECT_A, "terminal", _at(7), _at(12)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert (blocks[0].start_time, blocks[0].end_time) == (_at(0), _at(12))


class TestChronologicalOrdering:
    def test_out_of_order_input_is_sorted_internally_before_merging(self):
        """If the function assumed pre-sorted input, feeding rows in reverse
        chronological order would compute a nonsensical negative gap against
        the wrong "previous" row and produce two blocks. Sorting internally
        collapses them into one, matching the same rows given in order."""
        rows = [
            _row(PROJECT_A, "vscode", _at(22), _at(30)),
            _row(PROJECT_A, "vscode", _at(0), _at(10)),
            _row(PROJECT_A, "terminal", _at(12), _at(20)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert blocks[0].start_time == _at(0)
        assert blocks[0].end_time == _at(30)
        assert blocks[0].apps == ["vscode", "terminal"]

    def test_output_blocks_are_sorted_by_start_time_across_projects(self):
        rows = [
            _row(PROJECT_B, "terminal", _at(100), _at(105)),
            _row(PROJECT_A, "vscode", _at(0), _at(5)),
        ]

        blocks = aggregate_local_activity(rows)

        assert [block.project for block in blocks] == [PROJECT_A, PROJECT_B]


class TestLargeGapWithinSameProject:
    def test_multi_hour_gap_splits_into_separate_blocks(self):
        rows = [
            _row(PROJECT_A, "vscode", _at(0), _at(30)),
            _row(PROJECT_A, "vscode", _at(0) + timedelta(hours=3), _at(0) + timedelta(hours=3, minutes=30)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2
        assert blocks[0].duration == timedelta(minutes=30)
        assert blocks[1].duration == timedelta(minutes=30)


class TestTimezoneAwareDatetimes:
    """Every other test above uses naive datetimes for brevity, but
    tracker_sync's real rows come from a DateTime(timezone=True) column, so
    they'll be timezone-aware in production. Comparing an aware and a naive
    datetime raises TypeError, so this confirms merging (and the strict gap
    boundary) works correctly end to end when every datetime involved is
    aware, not just that it happens to work with naive ones."""

    @staticmethod
    def _aware_at(minute_offset: int) -> datetime:
        return datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=minute_offset)

    def test_aware_rows_with_small_gap_merge_into_one_block(self):
        rows = [
            _row(PROJECT_A, "vscode", self._aware_at(0), self._aware_at(10)),
            _row(PROJECT_A, "terminal", self._aware_at(12), self._aware_at(20)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert blocks[0].start_time == self._aware_at(0)
        assert blocks[0].end_time == self._aware_at(20)

    def test_aware_rows_with_gap_of_exactly_threshold_split(self):
        first_end = self._aware_at(0)
        second_start = first_end + timedelta(minutes=MERGE_GAP_THRESHOLD_MINUTES)
        rows = [
            _row(PROJECT_A, "vscode", self._aware_at(-10), first_end),
            _row(PROJECT_A, "terminal", second_start, second_start + timedelta(minutes=5)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2


class TestIdleAbsorption:
    """Same 'one precise, tested meaning' standard as TestGapBoundary above, against
    MICRO_IDLE_ABSORB_SECONDS instead of MERGE_GAP_THRESHOLD_MINUTES: an idle row strictly shorter than the
    threshold is absorbed, one of exactly the threshold (or longer) is not."""

    def test_idle_just_under_the_threshold_is_absorbed_into_the_preceding_block(self):
        idle_duration = timedelta(seconds=MICRO_IDLE_ABSORB_SECONDS) - timedelta(milliseconds=1)
        rows = [
            _row(PROJECT_A, "vscode", _at(0), _at(5), SessionCategory.coding),
            _row(None, "loginwindow", _at(5), _at(5) + idle_duration, SessionCategory.idle),
            _row(PROJECT_B, "terminal", _at(5) + idle_duration, _at(10), SessionCategory.coding),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2
        assert blocks[0].project == PROJECT_A
        assert blocks[0].end_time == _at(5) + idle_duration
        assert blocks[1].project == PROJECT_B
        assert blocks[1].start_time == _at(5) + idle_duration

    def test_idle_of_exactly_the_threshold_is_not_absorbed(self):
        idle_duration = timedelta(seconds=MICRO_IDLE_ABSORB_SECONDS)
        rows = [
            _row(PROJECT_A, "vscode", _at(0), _at(5), SessionCategory.coding),
            _row(None, "loginwindow", _at(5), _at(5) + idle_duration, SessionCategory.idle),
            _row(PROJECT_B, "terminal", _at(5) + idle_duration + timedelta(seconds=1), _at(10), SessionCategory.coding),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 3
        assert blocks[1].category == SessionCategory.idle
