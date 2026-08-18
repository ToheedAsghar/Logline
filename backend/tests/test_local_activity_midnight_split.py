"""Test that activity blocks spanning a local midnight are cut into one block per local day."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.local_activity.aggregation import LocalActivityBlock, TitleCluster, local_date, split_blocks_at_local_midnight
from app.local_activity.classification import SessionCategory

KARACHI = ZoneInfo("Asia/Karachi")


def _block(start: datetime, end: datetime, **overrides) -> LocalActivityBlock:
    fields = {
        "project": "/Users/test/projects/logline",
        "start_time": start,
        "end_time": end,
        "duration": end - start,
        "apps": ["Code"],
        "category": SessionCategory.coding,
    }
    fields.update(overrides)
    return LocalActivityBlock(**fields)


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


class TestSplittingAtLocalMidnight:
    def test_block_spanning_local_midnight_becomes_two_blocks(self):
        """The real Aug 5->6 case: a 48-second Firefox session straddling local midnight in Karachi."""
        start = _utc(2026, 8, 5, 18, 59, 38)
        end = _utc(2026, 8, 5, 19, 0, 26)

        first, second = split_blocks_at_local_midnight([_block(start, end)], KARACHI)

        assert first.start_time == start
        assert first.end_time == _utc(2026, 8, 5, 19, 0, 0)
        assert second.start_time == _utc(2026, 8, 5, 19, 0, 0)
        assert second.end_time == end

    def test_the_two_pieces_land_on_consecutive_local_days(self):
        blocks = split_blocks_at_local_midnight(
            [_block(_utc(2026, 8, 5, 18, 59, 38), _utc(2026, 8, 5, 19, 0, 26))], KARACHI
        )

        assert [local_date(block.start_time, KARACHI).isoformat() for block in blocks] == [
            "2026-08-05",
            "2026-08-06",
        ]

    def test_total_duration_is_conserved_across_the_split(self):
        """Conservation matters: minute accounting downstream is derived from block spans."""
        original = _block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 5, 20, 0))

        pieces = split_blocks_at_local_midnight([original], KARACHI)

        assert sum((piece.duration for piece in pieces), timedelta()) == original.duration

    def test_each_piece_reports_a_duration_matching_its_own_span(self):
        pieces = split_blocks_at_local_midnight(
            [_block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 5, 20, 0))], KARACHI
        )

        assert all(piece.duration == piece.end_time - piece.start_time for piece in pieces)

    def test_block_wholly_inside_one_local_day_is_returned_unchanged(self):
        original = _block(_utc(2026, 8, 5, 6, 0), _utc(2026, 8, 5, 8, 0))

        assert split_blocks_at_local_midnight([original], KARACHI) == [original]

    def test_block_ending_exactly_at_local_midnight_is_not_split(self):
        """It occupies no time on the next day, so cutting it would create an empty second piece."""
        original = _block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 5, 19, 0))

        assert split_blocks_at_local_midnight([original], KARACHI) == [original]

    def test_block_starting_exactly_at_local_midnight_is_not_split(self):
        original = _block(_utc(2026, 8, 5, 19, 0), _utc(2026, 8, 5, 21, 0))

        assert split_blocks_at_local_midnight([original], KARACHI) == [original]

    def test_block_spanning_two_midnights_becomes_three_blocks(self):
        pieces = split_blocks_at_local_midnight(
            [_block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 7, 6, 0))], KARACHI
        )

        assert [local_date(piece.start_time, KARACHI).isoformat() for piece in pieces] == [
            "2026-08-05",
            "2026-08-06",
            "2026-08-07",
        ]

    def test_the_same_block_splits_at_a_different_instant_under_a_different_timezone(self):
        """Proves the cut follows `tz` rather than UTC -- the whole point of the fix."""
        block = _block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 5, 20, 0))

        karachi_pieces = split_blocks_at_local_midnight([block], KARACHI)
        utc_pieces = split_blocks_at_local_midnight([block], timezone.utc)

        assert len(karachi_pieces) == 2
        assert utc_pieces == [block]

    def test_pieces_are_returned_ordered_by_start_time(self):
        spanning = _block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 5, 20, 0))
        earlier = _block(_utc(2026, 8, 5, 6, 0), _utc(2026, 8, 5, 7, 0))

        pieces = split_blocks_at_local_midnight([spanning, earlier], KARACHI)

        assert [piece.start_time for piece in pieces] == sorted(piece.start_time for piece in pieces)


class TestSplitPiecesRetainEvidence:
    def test_title_seconds_are_apportioned_by_each_pieces_share_of_the_span(self):
        block = _block(
            _utc(2026, 8, 5, 18, 0),
            _utc(2026, 8, 5, 20, 0),
            title_digest=[TitleCluster(title="resolvers.py", seconds=7200.0)],
        )

        first, second = split_blocks_at_local_midnight([block], KARACHI)

        assert first.title_digest[0].seconds == 3600.0
        assert second.title_digest[0].seconds == 3600.0

    def test_apportioned_title_seconds_sum_back_to_the_original(self):
        block = _block(
            _utc(2026, 8, 5, 18, 30),
            _utc(2026, 8, 5, 20, 0),
            title_digest=[TitleCluster(title="resolvers.py", seconds=5400.0)],
        )

        pieces = split_blocks_at_local_midnight([block], KARACHI)

        assert sum(piece.title_digest[0].seconds for piece in pieces) == 5400.0

    def test_context_lists_are_present_on_both_pieces(self):
        block = _block(
            _utc(2026, 8, 5, 18, 0),
            _utc(2026, 8, 5, 20, 0),
            branches=["toheed/feature/pipeline-classify-evidence"],
            urls=["https://claude.ai/chat/abc"],
        )

        for piece in split_blocks_at_local_midnight([block], KARACHI):
            assert piece.branches == ["toheed/feature/pipeline-classify-evidence"]
            assert piece.urls == ["https://claude.ai/chat/abc"]

    def test_mutating_one_pieces_context_list_does_not_affect_the_other(self):
        """Pieces must not alias the original's lists, or downstream edits would leak between days."""
        block = _block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 5, 20, 0), branches=["main"])

        first, second = split_blocks_at_local_midnight([block], KARACHI)
        first.branches.append("other")

        assert second.branches == ["main"]

    def test_category_and_project_are_preserved_on_every_piece(self):
        block = _block(_utc(2026, 8, 5, 18, 0), _utc(2026, 8, 5, 20, 0), category=SessionCategory.admin)

        for piece in split_blocks_at_local_midnight([block], KARACHI):
            assert piece.category == SessionCategory.admin
            assert piece.project == "/Users/test/projects/logline"


class TestNaiveDatetimesStayMachineIndependent:
    def test_naive_block_spanning_midnight_splits_on_its_own_wall_clock(self):
        """A naive datetime is read as already local, so the result never depends on the host's timezone."""
        pieces = split_blocks_at_local_midnight(
            [_block(datetime(2026, 8, 5, 23, 30), datetime(2026, 8, 6, 0, 30))], KARACHI
        )

        assert [piece.start_time for piece in pieces] == [
            datetime(2026, 8, 5, 23, 30),
            datetime(2026, 8, 6, 0, 0),
        ]

    def test_local_date_of_a_naive_datetime_is_its_own_date(self):
        assert local_date(datetime(2026, 8, 5, 23, 30), KARACHI).isoformat() == "2026-08-05"

    def test_local_date_of_an_aware_datetime_is_converted(self):
        assert local_date(_utc(2026, 8, 5, 19, 30), KARACHI).isoformat() == "2026-08-06"


class TestEmptyInput:
    def test_no_blocks_returns_no_blocks(self):
        assert split_blocks_at_local_midnight([], KARACHI) == []
