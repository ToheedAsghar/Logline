"""Tests for the category-aware behavior added to aggregate_local_activity (app/local_activity/aggregation.py):
grouping by (project, category) instead of project alone, named-meeting spans that merge across any gap
within a calendar day, and per-block title clustering.

`tests/test_local_activity_aggregation.py` covers the original project-only merge/gap-threshold behavior,
which still applies unchanged to every non-meeting category -- this file covers only what's new.
"""

from datetime import datetime, timedelta

from app.local_activity.aggregation import RawSessionRow, TitleCluster, aggregate_local_activity
from app.local_activity.classification import SessionCategory
from app.local_activity.constants import MERGE_GAP_THRESHOLD_MINUTES

PROJECT_A = "/Users/dev/projects/logline"


def _row(
    app: str,
    start: datetime,
    end: datetime,
    category: SessionCategory = SessionCategory.coding,
    project=PROJECT_A,
    window_title=None,
    meeting_name=None,
) -> RawSessionRow:
    return RawSessionRow(
        project=project,
        app=app,
        start_time=start,
        end_time=end,
        category=category,
        window_title=window_title,
        meeting_name=meeting_name,
    )


def _at(minute_offset: int) -> datetime:
    return datetime(2026, 8, 6, 9, 0) + timedelta(minutes=minute_offset)


class TestCategorySplitsGrouping:
    def test_same_project_different_category_never_merge_even_back_to_back(self):
        """This is the core Stage 3 fix: a meeting sitting next to coding work in the same project must not
        be fused into one block just because the gap is small."""
        rows = [
            _row("vscode", _at(0), _at(10), category=SessionCategory.coding),
            _row("chrome", _at(10), _at(20), category=SessionCategory.comms, project=None),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2
        categories = {block.category for block in blocks}
        assert categories == {SessionCategory.coding, SessionCategory.comms}

    def test_same_category_same_project_still_merges_under_the_ordinary_threshold(self):
        rows = [
            _row("vscode", _at(0), _at(10), category=SessionCategory.coding),
            _row("terminal", _at(12), _at(20), category=SessionCategory.coding),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert blocks[0].start_time == _at(0)
        assert blocks[0].end_time == _at(20)

    def test_different_categories_with_no_project_still_split_by_category(self):
        """project=None is now common (most browser activity); category alone must still separate them."""
        rows = [
            _row("chrome", _at(0), _at(10), category=SessionCategory.documentation, project=None),
            _row("chrome", _at(10), _at(20), category=SessionCategory.admin, project=None),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2


class TestNamedMeetingSpans:
    def test_named_meeting_merges_across_a_gap_larger_than_the_ordinary_threshold(self):
        """The person tabs away to code for a stretch well over MERGE_GAP_THRESHOLD_MINUTES, then returns to
        the same named meeting -- the block must still span first-instance to last-instance."""
        big_gap = MERGE_GAP_THRESHOLD_MINUTES + 45
        rows = [
            _row(
                "chrome", _at(0), _at(5), category=SessionCategory.meeting, project=None, meeting_name="Design Review"
            ),
            _row(
                "chrome",
                _at(5 + big_gap),
                _at(5 + big_gap + 10),
                category=SessionCategory.meeting,
                project=None,
                meeting_name="Design Review",
            ),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        block = blocks[0]
        assert block.category == SessionCategory.meeting
        assert block.project is None
        assert block.start_time == _at(0)
        assert block.end_time == _at(5 + big_gap + 10)
        assert block.meeting_name == "Design Review"

    def test_named_meeting_does_not_merge_across_a_calendar_day_boundary(self):
        day_one = datetime(2026, 8, 6, 23, 50)
        day_two = datetime(2026, 8, 7, 0, 5)
        rows = [
            _row("chrome", day_one, day_one + timedelta(minutes=5), category=SessionCategory.meeting, project=None,
                 meeting_name="Recurring Sync"),
            _row("chrome", day_two, day_two + timedelta(minutes=5), category=SessionCategory.meeting, project=None,
                 meeting_name="Recurring Sync"),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2

    def test_different_meeting_names_never_merge_even_when_adjacent(self):
        rows = [
            _row("chrome", _at(0), _at(5), category=SessionCategory.meeting, project=None, meeting_name="Standup"),
            _row("chrome", _at(5), _at(10), category=SessionCategory.meeting, project=None,
                 meeting_name="1:1 with manager"),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2

    def test_unnamed_meeting_sessions_fall_back_to_the_ordinary_gap_threshold(self):
        """Without a name to disambiguate occurrences, unlimited merging would risk fusing two genuinely
        different unnamed meetings on the same day -- so unnamed meetings merge conservatively instead."""
        big_gap = MERGE_GAP_THRESHOLD_MINUTES + 5
        rows = [
            _row("chrome", _at(0), _at(5), category=SessionCategory.meeting, project=None, meeting_name=None),
            _row("chrome", _at(5 + big_gap), _at(5 + big_gap + 5), category=SessionCategory.meeting, project=None,
                 meeting_name=None),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 2

    def test_unnamed_meeting_sessions_still_merge_under_the_ordinary_threshold(self):
        rows = [
            _row("chrome", _at(0), _at(5), category=SessionCategory.meeting, project=None, meeting_name=None),
            _row("chrome", _at(7), _at(12), category=SessionCategory.meeting, project=None, meeting_name=None),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1


class TestMeetingNameCarriesThroughToTheBlock:
    """meeting_name must survive onto the finished LocalActivityBlock (not just guide merging) -- matcher.py
    reads it off the block to check a calendar event's title before matching, so a bug here would silently
    reopen the wrong-event risk that check exists to close."""

    def test_unnamed_meeting_block_has_no_meeting_name(self):
        rows = [_row("chrome", _at(0), _at(5), category=SessionCategory.meeting, project=None, meeting_name=None)]

        blocks = aggregate_local_activity(rows)

        assert blocks[0].meeting_name is None

    def test_non_meeting_block_has_no_meeting_name(self):
        rows = [_row("vscode", _at(0), _at(10), category=SessionCategory.coding)]

        blocks = aggregate_local_activity(rows)

        assert blocks[0].meeting_name is None


class TestTitleClustering:
    def test_identical_titles_sum_minutes_into_one_cluster(self):
        rows = [
            _row("vscode", _at(0), _at(10), window_title="auth.py — logline"),
            _row("vscode", _at(10), _at(15), window_title="session.py — logline"),
            _row("vscode", _at(15), _at(25), window_title="auth.py — logline"),
        ]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        digest = {cluster.title: cluster.minutes for cluster in blocks[0].title_digest}
        assert digest == {"auth.py — logline": 20, "session.py — logline": 5}

    def test_clusters_are_sorted_by_minutes_descending(self):
        rows = [
            _row("vscode", _at(0), _at(5), window_title="short.py"),
            _row("vscode", _at(5), _at(35), window_title="long.py"),
        ]

        blocks = aggregate_local_activity(rows)

        assert blocks[0].title_digest == [
            TitleCluster(title="long.py", minutes=30),
            TitleCluster(title="short.py", minutes=5),
        ]

    def test_no_cap_on_the_number_of_distinct_title_clusters(self):
        rows = [_row("vscode", _at(i), _at(i + 1), window_title=f"file_{i}.py") for i in range(0, 20)]

        blocks = aggregate_local_activity(rows)

        assert len(blocks) == 1
        assert len(blocks[0].title_digest) == 20

    def test_rows_with_no_title_contribute_nothing_to_the_digest(self):
        rows = [_row("terminal", _at(0), _at(10), window_title=None)]

        blocks = aggregate_local_activity(rows)

        assert blocks[0].title_digest == []

    def test_blank_title_after_stripping_is_treated_as_no_title(self):
        rows = [_row("vscode", _at(0), _at(10), window_title="   ")]

        blocks = aggregate_local_activity(rows)

        assert blocks[0].title_digest == []

    def test_many_sub_minute_rows_of_the_same_title_still_sum_to_a_real_total(self):
        """Each row is individually under 30 seconds and would round to 0 minutes on its own -- summing
        the raw seconds across all four (80s total) before rounding once must still surface real signal
        instead of losing it to four separate zeros."""
        start = _at(0)
        rows = [
            _row(
                "vscode",
                start + timedelta(seconds=20 * i),
                start + timedelta(seconds=20 * (i + 1)),
                window_title="auth.py — logline",
            )
            for i in range(4)
        ]

        blocks = aggregate_local_activity(rows)

        assert blocks[0].title_digest == [TitleCluster(title="auth.py — logline", minutes=1)]

    def test_a_title_whose_real_total_rounds_to_zero_minutes_is_dropped(self):
        start = _at(0)
        rows = [
            _row("vscode", start, start + timedelta(seconds=10), window_title="flicker.py — logline"),
            _row("terminal", start + timedelta(seconds=10), start + timedelta(minutes=5)),
        ]

        blocks = aggregate_local_activity(rows)

        assert blocks[0].title_digest == []
