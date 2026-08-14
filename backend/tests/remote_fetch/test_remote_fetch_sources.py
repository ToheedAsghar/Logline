"""Tests for individual remote source fetchers and MCP response parsing."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.remote_fetch.mcp.calendar import CALENDAR_LIST_EVENTS_PAGE_SIZE, CalendarFetcher
from app.remote_fetch.mcp.github import GITHUB_MAX_PAGES, GITHUB_PER_PAGE, GitHubFetcher
from app.remote_fetch.mcp.jira import JiraFetcher
from app.remote_fetch.mcp.slack import SLACK_HISTORY_PAGE_LIMIT, SlackFetcher, resolve_connected_slack_user_id

SINCE = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _tool_result(payload) -> MagicMock:
    result = MagicMock()
    result.content = [MagicMock(text=json.dumps(payload))]
    return result


def _session_returning(payload_by_tool: dict) -> AsyncMock:
    """A mock MCP session dispatching on tool name, like the real one does."""

    session = AsyncMock()

    async def call_tool(name, arguments=None):
        if name not in payload_by_tool:
            raise AssertionError(f"unexpected tool call: {name}")
        return _tool_result(payload_by_tool[name])

    session.call_tool.side_effect = call_tool
    return session


# --- GitHub -----------------------------------------------------------------

# Shape of a github-mcp-server `list_commits` result: the REST payload, which
# is a bare array of commit objects.
GITHUB_COMMIT = {
    "sha": "a1b2c3d4e5f6",
    "commit": {
        "message": (
            "FIX(matching): treat a missing identity as never-match\n"
            "\n"
            "A None identity used to fall through to the wildcard branch, so a\n"
            "block with no resolved repo matched every event in the window."
        ),
        "author": {"name": "Toheed Asghar", "date": "2026-07-20T09:12:00Z"},
        "committer": {"name": "Toheed Asghar", "date": "2026-07-20T09:15:30Z"},
    },
    "author": {"login": "ToheedAsghar"},
}

GITHUB_COMMIT_NO_BODY = {
    "sha": "9f8e7d6c5b4a",
    "commit": {
        "message": "CHORE(deps): bump pytest to 9.1.1",
        "author": {"name": "Toheed Asghar", "date": "2026-07-21T11:00:00Z"},
        "committer": {"name": "Toheed Asghar", "date": "2026-07-21T11:00:00Z"},
    },
    "author": {"login": "ToheedAsghar"},
}

GITHUB_PULL_REQUEST = {
    "number": 42,
    "title": "Add Phase 3 remote fetching",
    "body": "Fills remote_events from all four sources.\n\nWhy now: Phase 4 has nothing to reconcile without it.",
    "state": "open",
    "created_at": "2026-07-18T08:00:00Z",
    "updated_at": "2026-07-22T16:45:00Z",
    "base": {"ref": "main"},
    "head": {"ref": "feature/remote-fetch"},
}


class TestGitHubFetcher:
    def _fetch(self, payloads, user_id=1, since=SINCE):
        session = _session_returning(payloads)
        return asyncio.run(GitHubFetcher().fetch_with_session(session, user_id, since)), session

    def test_commit_summary_is_subject_and_description_is_body(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch({"list_commits": [GITHUB_COMMIT], "list_pull_requests": []})

        commit = next(event for event in data.events if event.event_type == "commit")
        assert commit.summary == "FIX(matching): treat a missing identity as never-match"
        assert commit.description is not None
        assert commit.description.startswith("A None identity used to fall through")
        # The subject must not be repeated into the description.
        assert "treat a missing identity" not in commit.description

    def test_commit_without_a_body_has_no_description(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch({"list_commits": [GITHUB_COMMIT_NO_BODY], "list_pull_requests": []})

        commit = next(event for event in data.events if event.event_type == "commit")
        assert commit.summary == "CHORE(deps): bump pytest to 9.1.1"
        # Absent, not a restatement of the summary.
        assert commit.description is None

    def test_remote_project_id_is_the_repo_we_queried(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch({"list_commits": [GITHUB_COMMIT], "list_pull_requests": [GITHUB_PULL_REQUEST]})

        assert {event.remote_project_id for event in data.events} == {"Toheed/logline"}

    def test_commit_occurred_at_uses_committer_date(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch({"list_commits": [GITHUB_COMMIT], "list_pull_requests": []})

        commit = next(event for event in data.events if event.event_type == "commit")
        assert commit.occurred_at == datetime(2026, 7, 20, 9, 15, 30, tzinfo=timezone.utc)
        assert commit.external_id == "a1b2c3d4e5f6"

    def test_pull_request_summary_is_structural_and_description_is_the_body(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch({"list_commits": [], "list_pull_requests": [GITHUB_PULL_REQUEST]})

        pull_request = next(event for event in data.events if event.event_type == "pull_request")
        assert pull_request.summary == "PR #42 [open] Add Phase 3 remote fetching"
        assert pull_request.description.startswith("Fills remote_events from all four sources.")
        assert pull_request.external_id == "Toheed/logline#42"
        # updated_at, not created_at -- a PR opened earlier but touched today
        # is today's evidence.
        assert pull_request.occurred_at == datetime(2026, 7, 22, 16, 45, tzinfo=timezone.utc)

    def test_merged_pull_request_reports_merged_not_closed(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        merged = {**GITHUB_PULL_REQUEST, "state": "closed", "merged_at": "2026-07-22T16:45:00Z"}
        data, _ = self._fetch({"list_commits": [], "list_pull_requests": [merged]})

        pull_request = next(event for event in data.events if event.event_type == "pull_request")
        assert "[merged]" in pull_request.summary

    def test_pull_requests_older_than_since_are_dropped(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        stale = {**GITHUB_PULL_REQUEST, "number": 7, "updated_at": "2026-06-01T10:00:00Z"}
        data, _ = self._fetch({"list_commits": [], "list_pull_requests": [stale]})

        assert data.events == []

    def test_since_is_passed_to_list_commits(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        _, session = self._fetch({"list_commits": [], "list_pull_requests": []})

        commit_call = next(
            call for call in session.call_tool.call_args_list if call.args[0] == "list_commits"
        )
        assert commit_call.kwargs["arguments"]["since"] == SINCE.isoformat()
        assert commit_call.kwargs["arguments"]["owner"] == "Toheed"
        assert commit_call.kwargs["arguments"]["repo"] == "logline"

    def test_discovery_path_scopes_search_to_the_authenticated_user(self, monkeypatch):
        """With no configured repos, scope comes from get_me -- never unscoped."""

        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: None)
        search_commit = {
            **GITHUB_COMMIT,
            "repository": {"full_name": "Arbisoft/other-repo"},
        }
        session = _session_returning(
            {
                "get_me": {"login": "ToheedAsghar"},
                "search_commits": {"total_count": 1, "items": [search_commit]},
                "search_pull_requests": {"total_count": 0, "items": []},
            }
        )
        data = asyncio.run(GitHubFetcher().fetch_with_session(session, 1, SINCE))

        search_call = next(
            call for call in session.call_tool.call_args_list if call.args[0] == "search_commits"
        )
        query = search_call.kwargs["arguments"]["query"]
        assert "author:ToheedAsghar" in query
        # committer-date:, never since: -- GitHub silently ignores since:.
        assert "committer-date:>=2026-07-01" in query
        assert "since:" not in query
        # Identity comes from the search result's own repository field.
        assert data.events[0].remote_project_id == "Arbisoft/other-repo"

    def test_discovery_recovers_repo_from_repository_url(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: None)
        pr_hit = {
            **GITHUB_PULL_REQUEST,
            "repository_url": "https://api.github.com/repos/Arbisoft/logline",
        }
        session = _session_returning(
            {
                "get_me": {"login": "ToheedAsghar"},
                "search_commits": {"items": []},
                "search_pull_requests": {"items": [pr_hit]},
            }
        )
        data = asyncio.run(GitHubFetcher().fetch_with_session(session, 1, SINCE))

        assert data.events[0].remote_project_id == "Arbisoft/logline"

    def test_no_login_means_no_events_rather_than_an_unscoped_search(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: None)
        session = _session_returning({"get_me": {}})

        data = asyncio.run(GitHubFetcher().fetch_with_session(session, 1, SINCE))

        assert data.events == []
        assert [call.args[0] for call in session.call_tool.call_args_list] == ["get_me"]

    def test_commit_pagination_hitting_the_page_cap_holds_the_high_water_mark(self, monkeypatch):
        """`list_commits` has no way to say "there's more" beyond a full last
        page, so a full page at GITHUB_MAX_PAGES must not let the mark
        advance past the oldest commit actually kept -- see github.py's
        `_fetch_repo_commits`.
        """

        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        base = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
        full_page = [
            {
                "sha": f"sha-{i}",
                "commit": {
                    "message": f"commit {i}",
                    "author": {"name": "Toheed Asghar", "date": (base + timedelta(minutes=i)).isoformat()},
                    "committer": {"name": "Toheed Asghar", "date": (base + timedelta(minutes=i)).isoformat()},
                },
            }
            for i in range(GITHUB_PER_PAGE)
        ]
        data, session = self._fetch({"list_commits": full_page, "list_pull_requests": []})

        commit_calls = [call for call in session.call_tool.call_args_list if call.args[0] == "list_commits"]
        assert len(commit_calls) == GITHUB_MAX_PAGES
        # Every page returned the same oldest commit (base), since this mock
        # ignores the page argument -- the override must be exactly that.
        assert data.fetched_through_override == base

    def test_a_single_partial_page_of_commits_does_not_hold_the_mark_back(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch({"list_commits": [GITHUB_COMMIT], "list_pull_requests": []})

        assert data.fetched_through_override is None

    def test_pull_request_page_cap_holds_the_high_water_mark(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        base = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
        full_page = [
            {
                **GITHUB_PULL_REQUEST,
                "number": 100 + index,
                "updated_at": (base + timedelta(minutes=index)).isoformat(),
            }
            for index in range(GITHUB_PER_PAGE)
        ]
        data, session = self._fetch({"list_commits": [], "list_pull_requests": full_page})

        pr_calls = [call for call in session.call_tool.call_args_list if call.args[0] == "list_pull_requests"]
        assert len(pr_calls) == GITHUB_MAX_PAGES
        assert data.fetched_through_override == base


# --- Jira -------------------------------------------------------------------

JIRA_ISSUE = {
    "key": "LOG-14",
    "fields": {
        "summary": "Remote fetching fills remote_events",
        "description": "We cannot reconcile anything until the staging table has real data in it.",
        "status": {"name": "In Progress"},
        "issuetype": {"name": "Story"},
        "assignee": {"displayName": "Toheed Asghar"},
        "created": "2026-07-10T09:00:00.000+0500",
        "updated": "2026-07-23T14:30:00.000+0500",
    },
}


class TestJiraFetcher:
    def _fetch(self, issues, user_id=1, since=SINCE, mapped=None, monkeypatch=None):
        monkeypatch.setattr(
            "app.remote_fetch.mcp.jira.get_mapped_remote_project_ids", lambda user_id, source: mapped or []
        )
        session = _session_returning({"jira_search": {"issues": issues}})
        return asyncio.run(JiraFetcher().fetch_with_session(session, user_id, since)), session

    def test_summary_is_structural_and_description_is_the_issue_description(self, monkeypatch):
        data, _ = self._fetch([JIRA_ISSUE], monkeypatch=monkeypatch)

        event = data.events[0]
        assert event.summary == "LOG-14 [In Progress] Remote fetching fills remote_events"
        assert event.description == "We cannot reconcile anything until the staging table has real data in it."

    def test_remote_project_id_is_the_issue_key_prefix(self, monkeypatch):
        data, _ = self._fetch([JIRA_ISSUE], monkeypatch=monkeypatch)

        assert data.events[0].remote_project_id == "LOG"

    def test_occurred_at_is_updated_and_respects_the_offset(self, monkeypatch):
        data, _ = self._fetch([JIRA_ISSUE], monkeypatch=monkeypatch)

        # 14:30 at +0500 is 09:30 UTC -- a naive parse would be five hours off.
        assert data.events[0].occurred_at == datetime(2026, 7, 23, 9, 30, tzinfo=timezone.utc)

    def test_external_id_is_stable_across_two_updates_to_one_issue(self, monkeypatch):
        second_update = {
            "key": "LOG-14",
            "fields": {**JIRA_ISSUE["fields"], "updated": "2026-07-24T10:00:00.000+0500"},
        }
        data, _ = self._fetch([JIRA_ISSUE, second_update], monkeypatch=monkeypatch)

        assert len(data.events) == 1
        assert data.events[0].external_id == "LOG-14"
        assert data.events[0].occurred_at == datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)

    def test_jql_falls_back_to_current_user_when_nothing_is_mapped(self, monkeypatch):
        _, session = self._fetch([], monkeypatch=monkeypatch)

        jql = session.call_tool.call_args_list[0].kwargs["arguments"]["jql"]
        assert "assignee = currentUser()" in jql
        assert "project in" not in jql
        assert 'updated >= "2026-07-01T00:00:00+00:00"' in jql
        # Stable pagination requires a deterministic order.
        assert jql.endswith("ORDER BY updated ASC, key ASC")

    def test_jql_scopes_to_mapped_projects_when_configured(self, monkeypatch):
        _, session = self._fetch([], mapped=["LOG", "OPS"], monkeypatch=monkeypatch)

        jql = session.call_tool.call_args_list[0].kwargs["arguments"]["jql"]
        assert 'project in ("LOG", "OPS")' in jql

    def test_a_malformed_project_key_is_skipped_rather_than_breaking_the_query(self, monkeypatch):
        """An unescaped, attacker- or fat-finger-controlled project key could
        break out of the quoted JQL list. Validating against the real Jira
        key shape and dropping anything else keeps the rest of the query
        (and the other, valid keys) intact.
        """

        _, session = self._fetch([], mapped=['LOG" OR 1=1 --', "OPS"], monkeypatch=monkeypatch)

        jql = session.call_tool.call_args_list[0].kwargs["arguments"]["jql"]
        assert 'project in ("OPS")' in jql
        assert "OR 1=1" not in jql

    def test_all_project_keys_malformed_falls_back_to_assignee_only(self, monkeypatch):
        _, session = self._fetch([], mapped=["not-a-key!"], monkeypatch=monkeypatch)

        jql = session.call_tool.call_args_list[0].kwargs["arguments"]["jql"]
        assert "project in" not in jql
        assert "assignee = currentUser()" in jql

    def test_flattened_issue_without_a_fields_wrapper_still_parses(self, monkeypatch):
        """mcp-atlassian sometimes returns simplified, already-flat issues."""

        flat = {
            "key": "LOG-15",
            "summary": "Flat shape",
            "description": "Still the why.",
            "status": "Done",
            "updated": "2026-07-23T14:30:00.000+0000",
        }
        data, _ = self._fetch([flat], monkeypatch=monkeypatch)

        assert data.events[0].summary == "LOG-15 [Done] Flat shape"
        assert data.events[0].description == "Still the why."


# --- Slack ------------------------------------------------------------------

SLACK_MESSAGE = {
    "type": "message",
    "user": "U04TOHEED",
    "text": "Pushed the remote-fetch branch, ready for review",
    "ts": "1784799000.123456",
}

SLACK_JOIN_NOTICE = {
    "type": "message",
    "subtype": "channel_join",
    "user": "U04TOHEED",
    "text": "<@U04TOHEED> has joined the channel",
    "ts": "1784798900.000100",
}


CONNECTED_SLACK_USER_ID = "U04TOHEED"


class TestSlackFetcher:
    def _fetch(self, messages, monkeypatch, mapped=None, since=SINCE, connected_user_id=CONNECTED_SLACK_USER_ID):
        monkeypatch.setattr(
            "app.remote_fetch.mcp.slack.get_mapped_remote_project_ids",
            lambda user_id, source: mapped or ["C123LOGLINE"],
        )
        monkeypatch.setattr(
            "app.remote_fetch.mcp.slack.resolve_connected_slack_user_id", lambda: connected_user_id
        )
        session = _session_returning({"slack_get_channel_history": {"ok": True, "messages": messages}})
        return asyncio.run(SlackFetcher().fetch_with_session(session, 1, since)), session

    def test_description_is_the_message_text_and_summary_is_structural(self, monkeypatch):
        data, _ = self._fetch([SLACK_MESSAGE], monkeypatch)

        event = data.events[0]
        # The human-authored content is the message itself, so it is the
        # description; the summary states who posted where.
        assert event.description == "Pushed the remote-fetch branch, ready for review"
        assert event.summary == "Message in C123LOGLINE by U04TOHEED"

    def test_remote_project_id_is_the_channel(self, monkeypatch):
        data, _ = self._fetch([SLACK_MESSAGE], monkeypatch)

        assert data.events[0].remote_project_id == "C123LOGLINE"
        assert data.events[0].external_id == "C123LOGLINE:1784799000.123456"

    def test_ts_parses_to_utc_preserving_sub_second_ordering(self, monkeypatch):
        data, _ = self._fetch([SLACK_MESSAGE], monkeypatch)

        assert data.events[0].occurred_at == datetime.fromtimestamp(1784799000.123456, tz=timezone.utc)

    def test_join_notices_are_not_recorded_as_work(self, monkeypatch):
        data, _ = self._fetch([SLACK_MESSAGE, SLACK_JOIN_NOTICE], monkeypatch)

        assert len(data.events) == 1
        assert data.events[0].external_id.endswith("1784799000.123456")

    def test_messages_at_or_before_since_are_filtered_client_side(self, monkeypatch):
        """The MCP tool has no `oldest` param, so this must happen locally."""

        old = {**SLACK_MESSAGE, "ts": "1780306200.000000"}
        data, _ = self._fetch([SLACK_MESSAGE, old], monkeypatch)

        assert [event.external_id for event in data.events] == ["C123LOGLINE:1784799000.123456"]

    def test_unreadable_channel_is_skipped_not_fatal(self, monkeypatch):
        monkeypatch.setattr(
            "app.remote_fetch.mcp.slack.get_mapped_remote_project_ids",
            lambda user_id, source: ["C_PRIVATE"],
        )
        monkeypatch.setattr(
            "app.remote_fetch.mcp.slack.resolve_connected_slack_user_id",
            lambda: CONNECTED_SLACK_USER_ID,
        )
        session = _session_returning(
            {"slack_get_channel_history": {"ok": False, "error": "not_in_channel"}}
        )

        data = asyncio.run(SlackFetcher().fetch_with_session(session, 1, SINCE))

        assert data.events == []

    def test_messages_from_other_users_are_not_recorded(self, monkeypatch):
        """The bot's shared credentials can read everyone's messages in a
        channel, but only the connected user's own messages are their
        evidence.
        """

        other_users_message = {**SLACK_MESSAGE, "user": "U09SOMEONEELSE", "ts": "1784799100.000000"}
        data, _ = self._fetch([SLACK_MESSAGE, other_users_message], monkeypatch)

        assert [event.external_id for event in data.events] == ["C123LOGLINE:1784799000.123456"]

    def test_resolve_connected_slack_user_id_returns_none(self):
        """Per-user Slack identity resolution is not yet implemented, so resolution returns None."""
        assert resolve_connected_slack_user_id() is None

    def test_missing_connected_user_id_skips_the_source_entirely(self, monkeypatch):
        """Without a known identity to filter on, over-collecting everyone's
        messages is worse than fetching nothing -- the source is skipped by default.
        """

        monkeypatch.setattr(
            "app.remote_fetch.mcp.slack.get_mapped_remote_project_ids",
            lambda user_id, source: ["C123LOGLINE"],
        )
        session = _session_returning({"slack_get_channel_history": {"ok": True, "messages": [SLACK_MESSAGE]}})

        data = asyncio.run(SlackFetcher().fetch_with_session(session, 1, SINCE))

        assert data.events == []
        # Never even asked for channel history.
        assert session.call_tool.call_args_list == []

    def test_a_full_page_of_new_messages_holds_the_high_water_mark_back(self, monkeypatch):
        """Slack's history tool exposes no cursor, so a full page means older
        messages in the window are unreachable -- the mark must not advance
        past the oldest one actually seen, or they are skipped forever.
        """

        messages = [
            {**SLACK_MESSAGE, "ts": f"{1784799000 + index}.000000"}
            for index in range(SLACK_HISTORY_PAGE_LIMIT)
        ]
        data, _ = self._fetch(messages, monkeypatch)

        assert len(data.events) == SLACK_HISTORY_PAGE_LIMIT
        assert data.fetched_through_override == datetime.fromtimestamp(1784799000.0, tz=timezone.utc)

    def test_a_mixed_full_page_holds_the_mark_at_the_oldest_message(self, monkeypatch):
        old_timestamp = 1751328000.0
        messages = [
            {**SLACK_MESSAGE, "ts": f"{old_timestamp:.6f}"},
            *[
                {**SLACK_MESSAGE, "ts": f"{1784799000 + index}.000000"}
                for index in range(1, SLACK_HISTORY_PAGE_LIMIT)
            ],
        ]
        data, _ = self._fetch(messages, monkeypatch)

        assert data.fetched_through_override == datetime.fromtimestamp(old_timestamp, tz=timezone.utc)

    def test_a_partial_page_does_not_hold_the_mark_back(self, monkeypatch):
        data, _ = self._fetch([SLACK_MESSAGE], monkeypatch)

        assert data.fetched_through_override is None


# --- Calendar ---------------------------------------------------------------

CALENDAR_MEETING = {
    "id": "evt-standup-0723",
    "summary": "Phase 3 design review",
    "description": "Walk through the fetch-state schema before we build it.",
    "start": {"dateTime": "2026-07-23T09:00:00+05:00"},
    "end": {"dateTime": "2026-07-23T09:45:00+05:00"},
    "attendees": [
        {"email": "toheed.asghar@arbisoft.com", "self": True, "responseStatus": "accepted"},
        {"email": "teammate@arbisoft.com", "responseStatus": "accepted"},
    ],
    "organizer": {"email": "teammate@arbisoft.com"},
}

CALENDAR_WORKING_LOCATION = {
    "id": "evt-home-0723",
    "summary": "Home",
    "eventType": "workingLocation",
    "start": {"date": "2026-07-23"},
}


class TestCalendarFetcher:
    def _fetch(self, events, since=SINCE):
        session = _session_returning({"list-events": {"events": events}})
        return asyncio.run(CalendarFetcher().fetch_with_session(session, 1, since)), session

    def test_summary_is_structural_and_description_is_the_agenda(self):
        data, _ = self._fetch([CALENDAR_MEETING])

        event = data.events[0]
        assert event.summary == "Phase 3 design review (2 attendees)"
        assert event.description == "Walk through the fetch-state schema before we build it."

    def test_remote_project_id_is_none_because_a_meeting_has_no_project(self):
        data, _ = self._fetch([CALENDAR_MEETING])

        # matcher.py treats None as never-match, which is the correct
        # conservative outcome -- better than a guess derived from the title.
        assert data.events[0].remote_project_id is None

    def test_occurred_at_converts_the_offset_to_utc(self):
        data, _ = self._fetch([CALENDAR_MEETING])

        assert data.events[0].occurred_at == datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)

    def test_working_location_entries_are_not_evidence(self):
        data, _ = self._fetch([CALENDAR_MEETING, CALENDAR_WORKING_LOCATION])

        assert [event.external_id for event in data.events] == ["evt-standup-0723"]

    def test_a_meeting_this_user_declined_is_not_their_evidence(self):
        declined = {
            **CALENDAR_MEETING,
            "id": "evt-declined",
            "attendees": [
                {"email": "toheed.asghar@arbisoft.com", "self": True, "responseStatus": "declined"},
            ],
        }
        data, _ = self._fetch([declined])

        assert data.events == []

    def test_time_bounds_carry_no_fractional_seconds(self):
        """The server rejects microseconds outright, and a rejected call looks
        the same as an empty calendar.
        """

        since = datetime(2026, 7, 1, 12, 30, 45, 987654, tzinfo=timezone.utc)
        _, session = self._fetch([], since=since)

        arguments = session.call_tool.call_args_list[0].kwargs["arguments"]
        assert arguments["timeMin"] == "2026-07-01T12:30:45"
        assert "." not in arguments["timeMax"]
        assert arguments["calendarId"] == "primary"

    def test_all_day_event_start_becomes_midnight_utc(self):
        all_day = {
            "id": "evt-allday",
            "summary": "Offsite",
            "start": {"date": "2026-07-23"},
            "end": {"date": "2026-07-24"},
        }
        data, _ = self._fetch([all_day])

        assert data.events[0].occurred_at == datetime(2026, 7, 23, 0, 0, tzinfo=timezone.utc)

    def test_recurring_event_occurrences_are_distinct_events(self):
        """Live testing confirmed `list-events` expands a recurring series into
        one row per occurrence (each with its own id and start time) rather
        than a single series-master row -- a behavior of this MCP server's
        `singleEvents=true` default that we don't control and can't disable
        via the tool's own schema. This pins that expectation with a mock so a
        future server upgrade that changes the default is caught here rather
        than silently collapsing e.g. a week of standups into one event.
        """

        occurrence_1 = {
            **CALENDAR_MEETING,
            "id": "standup_20260721T090000Z",
            "summary": "Daily standup",
            "recurringEventId": "standup",
            "start": {"dateTime": "2026-07-21T09:00:00+05:00"},
            "end": {"dateTime": "2026-07-21T09:15:00+05:00"},
        }
        occurrence_2 = {
            **CALENDAR_MEETING,
            "id": "standup_20260722T090000Z",
            "summary": "Daily standup",
            "recurringEventId": "standup",
            "start": {"dateTime": "2026-07-22T09:00:00+05:00"},
            "end": {"dateTime": "2026-07-22T09:15:00+05:00"},
        }
        data, _ = self._fetch([occurrence_1, occurrence_2])

        assert len(data.events) == 2
        assert {event.external_id for event in data.events} == {
            "standup_20260721T090000Z",
            "standup_20260722T090000Z",
        }

    def test_hitting_the_apis_opaque_page_size_holds_the_high_water_mark(self):
        """`list-events` exposes no maxResults/pageToken at all, so a response
        at Google's own default page size is the only truncation signal we
        get -- see calendar.py's module docstring and `fetch_with_session`.
        """

        base = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
        full_page = [
            {
                "id": f"evt-{i}",
                "summary": f"Meeting {i}",
                "start": {"dateTime": (base + timedelta(minutes=i)).isoformat()},
            }
            for i in range(CALENDAR_LIST_EVENTS_PAGE_SIZE)
        ]
        data, _ = self._fetch(full_page)

        assert len(data.events) == CALENDAR_LIST_EVENTS_PAGE_SIZE
        # The last (newest) event kept, not the first -- ascending sort means
        # a cap always drops the tail.
        assert data.fetched_through_override == base + timedelta(minutes=CALENDAR_LIST_EVENTS_PAGE_SIZE - 1)

    def test_a_response_under_the_page_size_does_not_hold_the_mark_back(self):
        data, _ = self._fetch([CALENDAR_MEETING])

        assert data.fetched_through_override is None


# --- Cross-source -----------------------------------------------------------


class TestEveryFetcherProducesSchemaShapedEvents:
    """Whatever the source, the output must slot straight into `remote_events`
    -- non-null source/event_type/external_id/occurred_at, and a raw_data dict
    (the column is NOT NULL).
    """

    @pytest.mark.parametrize(
        "fetcher_name",
        ["github", "jira", "slack", "calendar"],
    )
    def test_required_columns_are_populated(self, fetcher_name, monkeypatch):
        if fetcher_name == "github":
            monkeypatch.setattr(
                "app.remote_fetch.mcp.github.get_user_github_repos", lambda user_id: ["Toheed/logline"]
            )
            session = _session_returning(
                {"list_commits": [GITHUB_COMMIT], "list_pull_requests": [GITHUB_PULL_REQUEST]}
            )
            fetcher = GitHubFetcher()
        elif fetcher_name == "jira":
            monkeypatch.setattr(
                "app.remote_fetch.mcp.jira.get_mapped_remote_project_ids", lambda user_id, source: []
            )
            session = _session_returning({"jira_search": {"issues": [JIRA_ISSUE]}})
            fetcher = JiraFetcher()
        elif fetcher_name == "slack":
            monkeypatch.setattr(
                "app.remote_fetch.mcp.slack.get_mapped_remote_project_ids",
                lambda user_id, source: ["C123LOGLINE"],
            )
            monkeypatch.setattr(
                "app.remote_fetch.mcp.slack.resolve_connected_slack_user_id",
                lambda: CONNECTED_SLACK_USER_ID,
            )
            session = _session_returning(
                {"slack_get_channel_history": {"ok": True, "messages": [SLACK_MESSAGE]}}
            )
            fetcher = SlackFetcher()
        else:
            session = _session_returning({"list-events": {"events": [CALENDAR_MEETING]}})
            fetcher = CalendarFetcher()

        data = asyncio.run(fetcher.fetch_with_session(session, 1, SINCE))

        assert data.events, f"{fetcher_name} produced no events"
        for event in data.events:
            assert event.source == fetcher_name
            assert event.event_type
            assert event.external_id
            assert event.occurred_at.tzinfo is not None
            assert isinstance(event.raw_data, dict) and event.raw_data
