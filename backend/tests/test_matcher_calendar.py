"""Tests for the calendar time-window-only matching added to app/matching/matcher.py.

`resolve_project_identities` deliberately never returns a "calendar" identity (a meeting has no local
project), so before this addition a calendar event could never match any block -- the identity check in
`_is_match` always failed for it. This file covers the one deliberate exception: a Meeting-category block
matches a calendar event by time window alone. Every other (category, source) combination still goes
through `tests/test_matcher.py`'s unchanged identity+time rules -- this file only covers the new branch.
"""

from datetime import datetime, timedelta
from typing import Optional

from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory
from app.matching.matcher import MatchedGroup, RemoteEventData, ResolvedLocalBlock, match_local_blocks_to_remote_events


def _at(minute_offset: int) -> datetime:
    return datetime(2026, 8, 6, 9, 0) + timedelta(minutes=minute_offset)


def _meeting_block(start: int, end: int, meeting_name: Optional[str] = None) -> LocalActivityBlock:
    return LocalActivityBlock(
        project=None,
        start_time=_at(start),
        end_time=_at(end),
        duration=_at(end) - _at(start),
        apps=["chrome"],
        category=SessionCategory.meeting,
        meeting_name=meeting_name,
    )


def _coding_block(start: int, end: int, project: str = "/Users/dev/logline") -> LocalActivityBlock:
    return LocalActivityBlock(
        project=project,
        start_time=_at(start),
        end_time=_at(end),
        duration=_at(end) - _at(start),
        apps=["vscode"],
        category=SessionCategory.coding,
    )


def _calendar_event(minute_offset: int, external_id: str = "cal:evt:1", summary: str = "Design Review"):
    return RemoteEventData(
        external_id=external_id,
        source="calendar",
        remote_project_id=None,
        occurred_at=_at(minute_offset),
        event_type="meeting",
        summary=summary,
    )


class TestMeetingBlockMatchesCalendarByTimeAlone:
    def test_meeting_block_with_no_identities_still_matches_a_calendar_event_within_its_window(self):
        """resolve_project_identities never returns a calendar identity -- remote_identities is realistically
        always {} for a Meeting block, since it has no project. The match must still succeed."""
        block = _meeting_block(0, 60)
        event = _calendar_event(30)

        result = match_local_blocks_to_remote_events([ResolvedLocalBlock(block=block, remote_identities={})], [event])

        assert len(result.matched) == 1
        assert result.matched[0].block is block
        assert result.matched[0].events == [event]
        assert result.unmatched_blocks == []
        assert result.unmatched_events == []

    def test_meeting_block_matches_even_if_remote_identities_happens_to_hold_stale_values(self):
        """The calendar branch must skip the identity check entirely, not merely tolerate a None identity --
        this proves it does not accidentally require remote_identities['calendar'] to equal anything."""
        block = _meeting_block(0, 60)
        event = _calendar_event(10)

        result = match_local_blocks_to_remote_events(
            [ResolvedLocalBlock(block=block, remote_identities={"github": "owner/repo", "jira": None})], [event]
        )

        assert len(result.matched) == 1

    def test_meeting_block_still_respects_the_time_window_against_a_calendar_event(self):
        block = _meeting_block(0, 30)
        far_event = _calendar_event(200)

        result = match_local_blocks_to_remote_events(
            [ResolvedLocalBlock(block=block, remote_identities={})], [far_event]
        )

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [far_event]

    def test_non_meeting_block_still_never_matches_a_calendar_event(self):
        """The exception is scoped to Meeting blocks only -- a Coding block overlapping a calendar event in
        time must not match it, since it has no project identity to corroborate against."""
        block = _coding_block(0, 60)
        event = _calendar_event(30)

        result = match_local_blocks_to_remote_events([ResolvedLocalBlock(block=block, remote_identities={})], [event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [event]

    def test_meeting_block_does_not_match_a_non_calendar_event_via_the_new_branch(self):
        """The exception is scoped to source == "calendar" -- a Meeting block must not suddenly match a
        github event just because it lacks identities too."""
        block = _meeting_block(0, 60)
        github_event = RemoteEventData(
            external_id="gh:pr:1",
            source="github",
            remote_project_id="owner/repo",
            occurred_at=_at(30),
            event_type="pull_request",
        )

        result = match_local_blocks_to_remote_events(
            [ResolvedLocalBlock(block=block, remote_identities={})], [github_event]
        )

        assert result.matched == []
        assert result.unmatched_blocks == [block]

    def test_matched_group_result_type_is_unaffected_by_the_new_branch(self):
        block = _meeting_block(0, 60)
        event = _calendar_event(15)

        result = match_local_blocks_to_remote_events([ResolvedLocalBlock(block=block, remote_identities={})], [event])

        assert isinstance(result.matched[0], MatchedGroup)


class TestNamedMeetingBlockRequiresTitleCorrelation:
    """A named block (the common case -- meeting_name is set whenever the tracker could read a title) must
    correlate its name against a calendar event's summary, not just its time window. Otherwise two real
    meetings held back-to-back could both fall inside one block's window and the wrong one could match.
    """

    def test_two_back_to_back_meetings_each_match_only_their_own_calendar_event(self):
        standup = _meeting_block(0, 15, meeting_name="Team Standup")
        design_review = _meeting_block(15, 45, meeting_name="Design Review")
        standup_event = _calendar_event(5, external_id="cal:evt:standup", summary="Team Standup Meeting")
        design_event = _calendar_event(20, external_id="cal:evt:design", summary="Design Review")

        result = match_local_blocks_to_remote_events(
            [
                ResolvedLocalBlock(block=standup, remote_identities={}),
                ResolvedLocalBlock(block=design_review, remote_identities={}),
            ],
            [standup_event, design_event],
        )

        matched_by_name = {group.block.meeting_name: group.events for group in result.matched}
        assert matched_by_name["Team Standup"] == [standup_event]
        assert matched_by_name["Design Review"] == [design_event]

    def test_named_block_does_not_match_a_same_window_event_for_a_different_meeting(self):
        block = _meeting_block(0, 60, meeting_name="Design Review")
        wrong_event = _calendar_event(10, summary="Team Standup Meeting")

        result = match_local_blocks_to_remote_events(
            [ResolvedLocalBlock(block=block, remote_identities={})], [wrong_event]
        )

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [wrong_event]

    def test_title_correlation_is_a_case_insensitive_substring_in_either_direction(self):
        block = _meeting_block(0, 30, meeting_name="Team Standup")
        event = _calendar_event(10, summary="TEAM STANDUP MEETING")

        result = match_local_blocks_to_remote_events([ResolvedLocalBlock(block=block, remote_identities={})], [event])

        assert len(result.matched) == 1

    def test_unnamed_meeting_block_still_falls_back_to_time_only_matching(self):
        """meeting_name is None for an unnamed lobby/landing tab -- there is nothing to correlate against,
        so this one remaining case still matches by time alone, same as before this fix."""
        block = _meeting_block(0, 60)
        event = _calendar_event(30, summary="Something else entirely")

        result = match_local_blocks_to_remote_events([ResolvedLocalBlock(block=block, remote_identities={})], [event])

        assert len(result.matched) == 1
