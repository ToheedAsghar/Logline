"""Test that zero-duration tracker transitions cannot affect aggregate block boundaries."""

from datetime import datetime, timedelta, timezone

from app.local_activity.aggregation import RawSessionRow, aggregate_local_activity
from app.local_activity.classification import SessionCategory

PROJECT = "/Users/dev/projects/logline"
ANCHOR = datetime(2026, 8, 4, 12, 30, 48, tzinfo=timezone.utc)


def _row(
    project: str | None,
    app: str,
    start: datetime,
    end: datetime,
    category: SessionCategory = SessionCategory.coding,
    meeting_name: str | None = None,
) -> RawSessionRow:
    return RawSessionRow(
        project=project,
        app=app,
        start_time=start,
        end_time=end,
        category=category,
        meeting_name=meeting_name,
    )


def _seconds(offset: int) -> datetime:
    return ANCHOR + timedelta(seconds=offset)


def _overlapping_pairs(blocks) -> list[tuple[int, int]]:
    """Every pair of blocks whose measured windows overlap, by index."""
    pairs = []
    for i, a in enumerate(blocks):
        for j, b in enumerate(blocks[i + 1:], start=i + 1):
            if a.start_time < b.end_time and b.start_time < a.end_time:
                pairs.append((i, j))
    return pairs


class TestZeroDurationRowsNeverSplitABlock:
    def test_the_real_2026_08_04_overlap_no_longer_reproduces(self):
        """The exact row shape that produced the overlapping blocks 90 and 91 in production.

        A 13-minute project row, then a 2-minute row of the same key, with a zero-duration project-less row sharing the
        second row's start instant. All three are one continuous stretch of Coding.
        """
        rows = [
            _row(PROJECT, "Terminal", _seconds(0), _seconds(810)),
            _row(PROJECT, "Code", _seconds(810), _seconds(938)),
            _row(None, "Code", _seconds(810), _seconds(810)),
        ]

        blocks = aggregate_local_activity(rows)

        assert _overlapping_pairs(blocks) == []
        assert len(blocks) == 1
        assert blocks[0].start_time == _seconds(0)
        assert blocks[0].end_time == _seconds(938)
        assert blocks[0].project == PROJECT

    def test_a_zero_duration_row_between_two_same_key_rows_does_not_split_them(self):
        """Without the fix this emits two blocks; the zero-duration row is noise, not a boundary."""
        rows = [
            _row(PROJECT, "Code", _seconds(0), _seconds(600)),
            _row(None, "Antigravity IDE", _seconds(600), _seconds(600)),
            _row(PROJECT, "Code", _seconds(600), _seconds(1200)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert blocks[0].start_time == _seconds(0)
        assert blocks[0].end_time == _seconds(1200)

    def test_a_zero_duration_row_never_becomes_a_block_of_its_own(self):
        rows = [
            _row(PROJECT, "Code", _seconds(0), _seconds(600)),
            _row(None, "Terminal", _seconds(300), _seconds(300)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert blocks[0].project == PROJECT

    def test_a_run_made_only_of_zero_duration_rows_produces_no_blocks(self):
        rows = [
            _row(None, "Code", _seconds(0), _seconds(0)),
            _row(PROJECT, "Terminal", _seconds(1), _seconds(1)),
            _row(None, "Firefox", _seconds(2), _seconds(2), category=SessionCategory.admin),
        ]

        assert aggregate_local_activity(rows) == []

    def test_zero_duration_rows_contribute_no_measured_time(self):
        """The surviving block's duration must be the real rows' span only -- a dropped row cannot add time."""
        rows = [
            _row(PROJECT, "Code", _seconds(0), _seconds(600)),
            _row(None, "Terminal", _seconds(600), _seconds(600)),
            _row(PROJECT, "Code", _seconds(600), _seconds(900)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert blocks[0].duration == timedelta(seconds=900)


class TestRealBoundariesStillSplit:
    def test_a_genuinely_short_row_of_a_different_key_still_splits_the_block(self):
        """Only a literally zero-length row is a transition marker.

        One real second of other work is real.
        """
        rows = [
            _row(PROJECT, "Code", _seconds(0), _seconds(600)),
            _row(None, "Firefox", _seconds(600), _seconds(601), category=SessionCategory.admin),
            _row(PROJECT, "Code", _seconds(601), _seconds(1200)),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 3
        assert _overlapping_pairs(blocks) == []

    def test_a_zero_duration_named_meeting_row_still_anchors_the_meetings_span(self):
        """Pass 1 is deliberately unaffected -- a meeting's span reflects the whole call, so the earliest instance still
        anchors it even when that instance measured no time of its own."""
        rows = [
            _row(None, "Chrome", _seconds(0), _seconds(0), SessionCategory.meeting, meeting_name="Standup"),
            _row(None, "Chrome", _seconds(600), _seconds(1200), SessionCategory.meeting, meeting_name="Standup"),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert blocks[0].meeting_name == "Standup"
        assert blocks[0].start_time == _seconds(0)
        assert blocks[0].end_time == _seconds(1200)
