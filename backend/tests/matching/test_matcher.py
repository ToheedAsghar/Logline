"""
Tests for match_local_blocks_to_remote_events (app/matching/matcher.py), the
deterministic step that decides whether a local activity block and a remote
event belong together.

Pure logic, no I/O -- every case runs entirely against in-memory
ResolvedLocalBlock / RemoteEventData fixtures. Coverage follows the two
things that must never happen: matching across a project mismatch, and
matching outside the allowed time window (including the asymmetric buffer,
which only ever extends after a block's end_time, never before its
start_time).

No real LLM/MCP/database calls are made anywhere in this file.
"""

from datetime import datetime, timedelta, timezone

from app.local_activity.aggregation import LocalActivityBlock
from app.matching.constants import MATCH_BUFFER_MINUTES
from app.matching.matcher import MatchedGroup, RemoteEventData, ResolvedLocalBlock, match_local_blocks_to_remote_events

GITHUB_REPO = "ToheedAsghar/Logline"
OTHER_REPO = "ToheedAsghar/other-repo"


def _at(minute_offset: int) -> datetime:
    return datetime(2026, 7, 24, 9, 0) + timedelta(minutes=minute_offset)


def _block(start: int, end: int, project: str = "/Users/dev/logline") -> LocalActivityBlock:
    return LocalActivityBlock(
        project=project,
        start_time=_at(start),
        end_time=_at(end),
        duration=_at(end) - _at(start),
        apps=["vscode"],
    )


def _resolved(block: LocalActivityBlock, github: str = GITHUB_REPO) -> ResolvedLocalBlock:
    return ResolvedLocalBlock(block=block, remote_identities={"github": github, "jira": None, "slack": None})


def _event(
    minute_offset: int,
    external_id: str,
    remote_project_id: str = GITHUB_REPO,
    source: str = "github",
) -> RemoteEventData:
    return RemoteEventData(
        external_id=external_id,
        source=source,
        remote_project_id=remote_project_id,
        occurred_at=_at(minute_offset),
        event_type="commit",
    )


class TestExactMatches:
    def test_event_within_block_range_matches(self):
        block = _block(0, 30)
        event = _event(15, "sha-1")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == [MatchedGroup(block=block, events=[event])]
        assert result.unmatched_blocks == []
        assert result.unmatched_events == []

    def test_event_within_buffer_after_end_time_matches(self):
        block = _block(0, 30)
        event = _event(30 + MATCH_BUFFER_MINUTES - 1, "sha-2")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == [MatchedGroup(block=block, events=[event])]


class TestProjectMismatch:
    def test_time_within_range_but_project_mismatch_does_not_match(self):
        block = _block(0, 30)
        event = _event(15, "sha-4", remote_project_id=OTHER_REPO)

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [event]

    def test_source_with_no_resolved_identity_never_matches(self):
        """A missing/None resolved identity for a source is a reason to not
        match, never a wildcard that matches everything."""
        block = _block(0, 30)
        resolved = ResolvedLocalBlock(block=block, remote_identities={"github": None})
        event = _event(15, "sha-5")

        result = match_local_blocks_to_remote_events([resolved], [event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [event]


class TestTimeOutsideWindow:
    def test_event_exactly_at_buffer_boundary_does_not_match(self):
        """The buffer's upper bound is strictly exclusive, matching
        aggregation.py's merge-gap convention: exactly MATCH_BUFFER_MINUTES
        after end_time is treated as outside the window, not inside it."""
        block = _block(0, 30)
        event = _event(30 + MATCH_BUFFER_MINUTES, "sha-3")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [event]

    def test_project_match_but_time_outside_range_and_buffer_does_not_match(self):
        block = _block(0, 30)
        event = _event(30 + MATCH_BUFFER_MINUTES + 1, "sha-6")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [event]

    def test_buffer_only_applies_after_end_time_not_before_start_time(self):
        """An event 5 minutes before a block started is not "close enough" --
        there is no symmetric buffer before start_time, only after end_time."""
        block = _block(10, 30)
        event = _event(5, "sha-7")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [event]


class TestMultiplicity:
    def test_multiple_remote_events_matching_one_block(self):
        block = _block(0, 30)
        event_a = _event(5, "sha-8")
        event_b = _event(20, "sha-9")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event_a, event_b])

        assert len(result.matched) == 1
        assert result.matched[0].block == block
        assert set(e.external_id for e in result.matched[0].events) == {"sha-8", "sha-9"}
        assert result.unmatched_events == []

    def test_one_remote_event_matching_zero_blocks_stays_unmatched(self):
        block = _block(0, 30)
        unrelated_event = _event(9999, "sha-10")

        result = match_local_blocks_to_remote_events([_resolved(block)], [unrelated_event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [unrelated_event]


class TestEmptyInputs:
    def test_empty_blocks_and_events_returns_empty_result(self):
        result = match_local_blocks_to_remote_events([], [])

        assert result.matched == []
        assert result.unmatched_blocks == []
        assert result.unmatched_events == []

    def test_blocks_with_no_events_are_all_unmatched(self):
        block = _block(0, 30)

        result = match_local_blocks_to_remote_events([_resolved(block)], [])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == []

    def test_events_with_no_blocks_are_all_unmatched(self):
        event = _event(0, "sha-11")

        result = match_local_blocks_to_remote_events([], [event])

        assert result.matched == []
        assert result.unmatched_blocks == []
        assert result.unmatched_events == [event]


class TestTimezoneAwareDatetimes:
    """Every other test in this file uses naive datetimes for brevity, but
    the real callers matching feeds into -- tracker_sync and remote_events,
    both DateTime(timezone=True) columns -- produce timezone-aware
    datetimes. Comparing an aware and a naive datetime raises TypeError, so
    this confirms the matcher works correctly end to end when every
    datetime involved is aware, not just that it happens to work with
    naive ones."""

    @staticmethod
    def _aware_at(minute_offset: int) -> datetime:
        return datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=minute_offset)

    def _aware_block(self, start: int, end: int) -> LocalActivityBlock:
        return LocalActivityBlock(
            project="/Users/dev/logline",
            start_time=self._aware_at(start),
            end_time=self._aware_at(end),
            duration=self._aware_at(end) - self._aware_at(start),
            apps=["vscode"],
        )

    def _aware_event(
        self, minute_offset: int, external_id: str, remote_project_id: str = GITHUB_REPO
    ) -> RemoteEventData:
        return RemoteEventData(
            external_id=external_id,
            source="github",
            remote_project_id=remote_project_id,
            occurred_at=self._aware_at(minute_offset),
            event_type="commit",
        )

    def test_aware_event_within_block_range_matches(self):
        block = self._aware_block(0, 30)
        event = self._aware_event(15, "aware-sha-1")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == [MatchedGroup(block=block, events=[event])]

    def test_aware_event_outside_buffer_does_not_match(self):
        block = self._aware_block(0, 30)
        event = self._aware_event(30 + MATCH_BUFFER_MINUTES, "aware-sha-2")

        result = match_local_blocks_to_remote_events([_resolved(block)], [event])

        assert result.matched == []
        assert result.unmatched_blocks == [block]
        assert result.unmatched_events == [event]
