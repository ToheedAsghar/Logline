"""Tests for individual remote source fetchers and their REST API response parsing."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx
import pytest

from app.remote_fetch.base import SourceCredentials, SourceUnavailable
from app.remote_fetch.constants import MAX_EVENTS_PER_SOURCE
from app.remote_fetch.sources.calendar import CALENDAR_MAX_PAGES, CalendarFetcher
from app.remote_fetch.sources.github import GITHUB_MAX_PAGES, GITHUB_PER_PAGE, GitHubFetcher
from app.remote_fetch.sources.jira import JiraFetcher, _adf_to_plain_text, _issue_description
from app.remote_fetch.sources.slack import SlackFetcher

SINCE = datetime(2026, 7, 1, tzinfo=timezone.utc)
CREDENTIALS = SourceCredentials(access_token="test-token")

_DUMMY_REQUEST = httpx.Request("GET", "https://example.invalid")


def _response(payload: Any, status_code: int = 200, headers: Optional[dict] = None) -> httpx.Response:
    return httpx.Response(status_code, json=payload, headers=headers or {}, request=_DUMMY_REQUEST)


class _RecordedCall:
    def __init__(self, method: str, url: str, **kwargs: Any) -> None:
        self.method = method
        self.url = url
        self.kwargs = kwargs


class FakeAsyncClient:
    """Minimal stand-in for httpx.AsyncClient: dispatches GET/POST calls to a handler function.

    The handler receives (url, **kwargs) and returns an httpx.Response -- tests provide one
    handler per fixture and assert on `.calls` the same way the old MCP tests asserted on a mock
    session's `call_tool.call_args_list`.
    """

    def __init__(
        self,
        get_handler: Optional[Callable[..., httpx.Response]] = None,
        post_handler: Optional[Callable[..., httpx.Response]] = None,
    ) -> None:
        self._get_handler = get_handler
        self._post_handler = post_handler
        self.calls: list[_RecordedCall] = []

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(_RecordedCall("GET", url, **kwargs))
        if self._get_handler is None:
            raise AssertionError(f"unexpected GET call: {url}")
        return self._get_handler(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(_RecordedCall("POST", url, **kwargs))
        if self._post_handler is None:
            raise AssertionError(f"unexpected POST call: {url}")
        return self._post_handler(url, **kwargs)


def _by_url_suffix(mapping: dict[str, Any]) -> Callable[..., httpx.Response]:
    """Build a handler that returns a fixture based on which mapping key the URL ends with."""

    def handler(url: str, **kwargs: Any) -> httpx.Response:
        for suffix, payload in mapping.items():
            if url.endswith(suffix):
                return _response(payload)
        raise AssertionError(f"no fixture registered for URL {url}")

    return handler


# --- GitHub -----------------------------------------------------------------

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
    def _fetch(self, commits, pull_requests, user_id=1, since=SINCE):
        client = FakeAsyncClient(
            get_handler=_by_url_suffix(
                {"/commits": commits, "/pulls": pull_requests, "/user": {"login": "ToheedAsghar"}}
            )
        )
        data = asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, user_id, since))
        return data, client

    def test_commit_summary_is_subject_and_description_is_body(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch([GITHUB_COMMIT], [])

        commit = next(event for event in data.events if event.event_type == "commit")
        assert commit.summary == "FIX(matching): treat a missing identity as never-match"
        assert commit.description is not None
        assert commit.description.startswith("A None identity used to fall through")
        assert "treat a missing identity" not in commit.description

    def test_commit_without_a_body_has_no_description(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch([GITHUB_COMMIT_NO_BODY], [])

        commit = next(event for event in data.events if event.event_type == "commit")
        assert commit.summary == "CHORE(deps): bump pytest to 9.1.1"
        assert commit.description is None

    def test_remote_project_id_is_the_repo_we_queried(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch([GITHUB_COMMIT], [GITHUB_PULL_REQUEST])

        assert {event.remote_project_id for event in data.events} == {"Toheed/logline"}

    def test_commit_occurred_at_uses_committer_date(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch([GITHUB_COMMIT], [])

        commit = next(event for event in data.events if event.event_type == "commit")
        assert commit.occurred_at == datetime(2026, 7, 20, 9, 15, 30, tzinfo=timezone.utc)
        assert commit.external_id == "a1b2c3d4e5f6"

    def test_pull_request_summary_is_structural_and_description_is_the_body(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch([], [GITHUB_PULL_REQUEST])

        pull_request = next(event for event in data.events if event.event_type == "pull_request")
        assert pull_request.summary == "PR #42 [open] Add Phase 3 remote fetching"
        assert pull_request.description.startswith("Fills remote_events from all four sources.")
        assert pull_request.external_id == "Toheed/logline#42"
        assert pull_request.occurred_at == datetime(2026, 7, 22, 16, 45, tzinfo=timezone.utc)

    def test_merged_pull_request_reports_merged_not_closed(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        merged = {**GITHUB_PULL_REQUEST, "state": "closed", "merged_at": "2026-07-22T16:45:00Z"}
        data, _ = self._fetch([], [merged])

        pull_request = next(event for event in data.events if event.event_type == "pull_request")
        assert "[merged]" in pull_request.summary

    def test_pull_requests_older_than_since_are_dropped(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        stale = {**GITHUB_PULL_REQUEST, "number": 7, "updated_at": "2026-06-01T10:00:00Z"}
        data, _ = self._fetch([], [stale])

        assert data.events == []

    def test_since_and_auth_headers_are_sent_on_the_commits_request(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        _, client = self._fetch([], [])

        commit_call = next(call for call in client.calls if call.url.endswith("/commits"))
        assert commit_call.kwargs["params"]["since"] == SINCE.isoformat()
        assert commit_call.url == "https://api.github.com/repos/Toheed/logline/commits"
        assert commit_call.kwargs["headers"]["Authorization"] == "Bearer test-token"

    def test_discovery_path_scopes_search_to_the_authenticated_user(self, monkeypatch):
        """With no configured repos, scope comes from /user -- never unscoped."""

        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: None)
        search_commit = {**GITHUB_COMMIT, "repository": {"full_name": "Arbisoft/other-repo"}}
        client = FakeAsyncClient(
            get_handler=_by_url_suffix(
                {
                    "/user": {"login": "ToheedAsghar"},
                    "/search/commits": {"total_count": 1, "items": [search_commit]},
                    "/search/issues": {"total_count": 0, "items": []},
                }
            )
        )
        data = asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        search_call = next(call for call in client.calls if call.url.endswith("/search/commits"))
        query = search_call.kwargs["params"]["q"]
        assert "author:ToheedAsghar" in query
        assert "committer-date:>=2026-07-01" in query
        assert "since:" not in query
        assert data.events[0].remote_project_id == "Arbisoft/other-repo"

    def test_discovery_recovers_repo_from_repository_url(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: None)
        pr_hit = {**GITHUB_PULL_REQUEST, "repository_url": "https://api.github.com/repos/Arbisoft/logline"}
        client = FakeAsyncClient(
            get_handler=_by_url_suffix(
                {
                    "/user": {"login": "ToheedAsghar"},
                    "/search/commits": {"items": []},
                    "/search/issues": {"items": [pr_hit]},
                }
            )
        )
        data = asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert data.events[0].remote_project_id == "Arbisoft/logline"

    def test_discovered_merged_pr_reports_merged_not_open(self, monkeypatch):
        """`/search/issues` is issue-shaped: merge state lives at `pull_request.merged_at`, not
        top-level like the full `/pulls` response `_pull_request_event` was originally written
        against. Without lifting it, every search-discovered merged PR looks open/closed instead.
        """

        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: None)
        search_hit = {
            "number": 77,
            "title": "Add Phase 3 remote fetching",
            "body": "Fills remote_events from all four sources.",
            "state": "closed",
            "created_at": "2026-07-18T08:00:00Z",
            "updated_at": "2026-07-22T16:45:00Z",
            "repository_url": "https://api.github.com/repos/Arbisoft/logline",
            "pull_request": {"merged_at": "2026-07-22T16:45:00Z"},
        }
        client = FakeAsyncClient(
            get_handler=_by_url_suffix(
                {
                    "/user": {"login": "ToheedAsghar"},
                    "/search/commits": {"items": []},
                    "/search/issues": {"items": [search_hit]},
                }
            )
        )
        data = asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert data.events[0].match_keys["state"] == "merged"

    def test_no_login_means_no_events_rather_than_an_unscoped_search(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: None)
        client = FakeAsyncClient(get_handler=_by_url_suffix({"/user": {}}))

        data = asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert data.events == []
        assert [call.url for call in client.calls] == ["https://api.github.com/user"]

    def test_commit_pagination_hitting_the_page_cap_holds_the_high_water_mark(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
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
        data, client = self._fetch(full_page, [])

        commit_calls = [call for call in client.calls if call.url.endswith("/commits")]
        assert len(commit_calls) == GITHUB_MAX_PAGES
        # /commits is newest-first, so whatever's beyond the page cap is *older* than every fetched
        # commit -- the mark must hold at `since`, not advance to the oldest fetched commit, or that
        # unfetched older window is lost for good.
        assert data.fetched_through_override == SINCE

    def test_a_single_partial_page_of_commits_does_not_hold_the_mark_back(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        data, _ = self._fetch([GITHUB_COMMIT], [])

        assert data.fetched_through_override is None

    def test_pull_request_page_cap_holds_the_high_water_mark(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        base = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
        full_page = [
            {**GITHUB_PULL_REQUEST, "number": 100 + index, "updated_at": (base + timedelta(minutes=index)).isoformat()}
            for index in range(GITHUB_PER_PAGE)
        ]
        data, client = self._fetch([], full_page)

        pr_calls = [call for call in client.calls if call.url.endswith("/pulls")]
        assert len(pr_calls) == GITHUB_MAX_PAGES
        # Same reasoning as the commit page-cap test: sorted newest-updated-first, so the mark must
        # hold at `since` rather than advance to the oldest fetched PR's timestamp.
        assert data.fetched_through_override == SINCE

    def test_empty_repo_409_is_treated_as_no_commits_not_a_fatal_error(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        client = FakeAsyncClient(
            get_handler=lambda url, **kwargs: (
                _response({"message": "Git Repository is empty."}, status_code=409)
                if url.endswith("/commits")
                else _response([])
            )
        )
        data = asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert data.events == []

    def test_rate_limit_exhausted_raises_source_unavailable_not_a_crash(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        client = FakeAsyncClient(
            get_handler=lambda url, **kwargs: _response(
                {"message": "API rate limit exceeded"},
                status_code=403,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1784800000"},
            )
        )

        with pytest.raises(SourceUnavailable):
            asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

    def test_low_remaining_rate_limit_logs_a_warning_but_still_returns_events(self, monkeypatch, caplog):
        monkeypatch.setattr("app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"])
        client = FakeAsyncClient(
            get_handler=_by_url_suffix({"/commits": [GITHUB_COMMIT], "/pulls": []}),
        )
        # Patch the handler to attach a low-remaining header on every response.
        original_get = client.get

        async def get_with_low_remaining(url, **kwargs):
            response = await original_get(url, **kwargs)
            return httpx.Response(
                response.status_code,
                json=response.json(),
                headers={"X-RateLimit-Remaining": "5"},
                request=_DUMMY_REQUEST,
            )

        client.get = get_with_low_remaining

        with caplog.at_level("WARNING"):
            data = asyncio.run(GitHubFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert data.events
        assert any("github_rate_limit_low" in record.message for record in caplog.records)


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

JIRA_ADF_DESCRIPTION = {
    "type": "doc",
    "version": 1,
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "We cannot reconcile anything until"}]},
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "the staging table has data"}]}
                    ],
                }
            ],
        },
    ],
}

JIRA_ACCESSIBLE_RESOURCES = [{"id": "cloud-id-123", "url": "https://arbisoft.atlassian.net", "name": "Arbisoft"}]


class TestJiraFetcher:
    def _client(self, issues, monkeypatch=None, cached_cloud_id=None, mapped=None):
        if monkeypatch is not None:
            monkeypatch.setattr(
                "app.remote_fetch.sources.jira.get_mapped_remote_project_ids", lambda user_id, source: mapped or []
            )
            monkeypatch.setattr(
                "app.remote_fetch.sources.jira.get_cached_jira_cloud_id", lambda user_id: cached_cloud_id
            )
            monkeypatch.setattr(
                "app.remote_fetch.sources.jira.set_cached_jira_cloud_id", lambda user_id, cloud_id: None
            )

        return FakeAsyncClient(
            get_handler=_by_url_suffix({"/accessible-resources": JIRA_ACCESSIBLE_RESOURCES}),
            post_handler=lambda url, **kwargs: _response({"issues": issues}),
        )

    def _fetch(self, issues, user_id=1, since=SINCE, mapped=None, monkeypatch=None, cached_cloud_id="cloud-id-123"):
        client = self._client(issues, monkeypatch=monkeypatch, cached_cloud_id=cached_cloud_id, mapped=mapped)
        data = asyncio.run(JiraFetcher().fetch_with_client(client, CREDENTIALS, user_id, since))
        return data, client

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

        assert data.events[0].occurred_at == datetime(2026, 7, 23, 9, 30, tzinfo=timezone.utc)

    def test_external_id_is_stable_across_two_updates_to_one_issue(self, monkeypatch):
        second_update = {"key": "LOG-14", "fields": {**JIRA_ISSUE["fields"], "updated": "2026-07-24T10:00:00.000+0500"}}
        data, _ = self._fetch([JIRA_ISSUE, second_update], monkeypatch=monkeypatch)

        assert len(data.events) == 1
        assert data.events[0].external_id == "LOG-14"
        assert data.events[0].occurred_at == datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)

    def test_jql_falls_back_to_current_user_when_nothing_is_mapped(self, monkeypatch):
        _, client = self._fetch([], monkeypatch=monkeypatch)

        post_call = next(call for call in client.calls if call.method == "POST")
        jql = post_call.kwargs["json"]["jql"]
        assert "assignee = currentUser()" in jql
        assert "project in" not in jql
        # Quoted "yyyy-MM-dd HH:mm" -- JQL date literals don't accept an ISO 8601 "T"/seconds/offset.
        assert 'updated >= "2026-07-01 00:00"' in jql
        assert jql.endswith("ORDER BY updated ASC, key ASC")

    def test_jql_scopes_to_mapped_projects_when_configured(self, monkeypatch):
        _, client = self._fetch([], mapped=["LOG", "OPS"], monkeypatch=monkeypatch)

        jql = next(call for call in client.calls if call.method == "POST").kwargs["json"]["jql"]
        assert 'project in ("LOG", "OPS")' in jql

    def test_a_malformed_project_key_is_skipped_rather_than_breaking_the_query(self, monkeypatch):
        _, client = self._fetch([], mapped=['LOG" OR 1=1 --', "OPS"], monkeypatch=monkeypatch)

        jql = next(call for call in client.calls if call.method == "POST").kwargs["json"]["jql"]
        assert 'project in ("OPS")' in jql
        assert "OR 1=1" not in jql

    def test_all_project_keys_malformed_falls_back_to_assignee_only(self, monkeypatch):
        _, client = self._fetch([], mapped=["not-a-key!"], monkeypatch=monkeypatch)

        jql = next(call for call in client.calls if call.method == "POST").kwargs["json"]["jql"]
        assert "project in" not in jql
        assert "assignee = currentUser()" in jql

    def test_flattened_issue_without_a_fields_wrapper_still_parses(self, monkeypatch):
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

    def test_real_adf_description_is_walked_to_plain_text(self, monkeypatch):
        issue = {"key": "LOG-16", "fields": {**JIRA_ISSUE["fields"], "description": JIRA_ADF_DESCRIPTION}}
        data, _ = self._fetch([issue], monkeypatch=monkeypatch)

        assert data.events[0].description == "We cannot reconcile anything until\nthe staging table has data"

    def test_cached_cloud_id_skips_the_accessible_resources_call(self, monkeypatch):
        _, client = self._fetch([], monkeypatch=monkeypatch, cached_cloud_id="cloud-id-123")

        assert not any(call.url.endswith("/accessible-resources") for call in client.calls)
        search_call = next(call for call in client.calls if call.method == "POST")
        assert "/ex/jira/cloud-id-123/rest/api/3/search" in search_call.url

    def test_missing_cached_cloud_id_discovers_and_caches_it(self, monkeypatch):
        cached_calls = []
        monkeypatch.setattr("app.remote_fetch.sources.jira.get_mapped_remote_project_ids", lambda user_id, source: [])
        monkeypatch.setattr("app.remote_fetch.sources.jira.get_cached_jira_cloud_id", lambda user_id: None)
        monkeypatch.setattr(
            "app.remote_fetch.sources.jira.set_cached_jira_cloud_id",
            lambda user_id, cloud_id: cached_calls.append((user_id, cloud_id)),
        )
        client = FakeAsyncClient(
            get_handler=_by_url_suffix({"/accessible-resources": JIRA_ACCESSIBLE_RESOURCES}),
            post_handler=lambda url, **kwargs: _response({"issues": []}),
        )

        asyncio.run(JiraFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert any(call.url.endswith("/accessible-resources") for call in client.calls)
        assert cached_calls == [(1, "cloud-id-123")]

    def test_no_accessible_resources_raises_source_unavailable(self, monkeypatch):
        monkeypatch.setattr("app.remote_fetch.sources.jira.get_mapped_remote_project_ids", lambda user_id, source: [])
        monkeypatch.setattr("app.remote_fetch.sources.jira.get_cached_jira_cloud_id", lambda user_id: None)
        client = FakeAsyncClient(get_handler=_by_url_suffix({"/accessible-resources": []}))

        with pytest.raises(SourceUnavailable):
            asyncio.run(JiraFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))


class TestAdfToPlainText:
    """Direct unit tests of the ADF walker, independent of the fetcher, so its node-type coverage
    is pinned regardless of how JiraFetcher wires it in.
    """

    def test_plain_string_description_still_works(self):

        assert _issue_description({"description": "just text"}) == "just text"

    def test_none_description_returns_none(self):

        assert _issue_description({}) is None

    def test_paragraphs_are_joined_with_newlines(self):

        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "second"}]},
            ],
        }
        assert _adf_to_plain_text(doc) == "first\nsecond"

    def test_hard_break_becomes_a_newline_within_a_paragraph(self):

        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "line one"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "line two"},
                    ],
                }
            ],
        }
        assert _adf_to_plain_text(doc) == "line one\nline two"

    def test_mention_renders_its_display_text(self):

        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "cc "},
                        {"type": "mention", "attrs": {"id": "abc", "text": "@Toheed"}},
                    ],
                }
            ],
        }
        assert _adf_to_plain_text(doc) == "cc @Toheed"

    def test_empty_document_returns_none_not_empty_string(self):

        assert _adf_to_plain_text({"type": "doc", "content": []}) is None

    def test_non_dict_input_returns_none(self):

        assert _adf_to_plain_text("not a document") is None


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
SLACK_CREDENTIALS = SourceCredentials(access_token="test-token", authed_user_id=CONNECTED_SLACK_USER_ID)


class TestSlackFetcher:
    def _fetch(self, messages, monkeypatch, mapped=None, since=SINCE, credentials=SLACK_CREDENTIALS):
        monkeypatch.setattr(
            "app.remote_fetch.sources.slack.get_mapped_remote_project_ids",
            lambda user_id, source: mapped or ["C123LOGLINE"],
        )
        client = FakeAsyncClient(
            get_handler=_by_url_suffix({"/conversations.history": {"ok": True, "messages": messages}})
        )
        data = asyncio.run(SlackFetcher().fetch_with_client(client, credentials, 1, since))
        return data, client

    def test_description_is_the_message_text_and_summary_is_structural(self, monkeypatch):
        data, _ = self._fetch([SLACK_MESSAGE], monkeypatch)

        event = data.events[0]
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

    def test_messages_at_or_before_since_are_filtered(self, monkeypatch):
        old = {**SLACK_MESSAGE, "ts": "1780306200.000000"}
        data, _ = self._fetch([SLACK_MESSAGE, old], monkeypatch)

        assert [event.external_id for event in data.events] == ["C123LOGLINE:1784799000.123456"]

    def test_since_is_sent_as_the_oldest_param(self, monkeypatch):
        _, client = self._fetch([], monkeypatch)

        history_call = next(call for call in client.calls if call.url.endswith("/conversations.history"))
        assert history_call.kwargs["params"]["oldest"] == f"{SINCE.timestamp():.6f}"

    def test_unreadable_channel_is_skipped_not_fatal(self, monkeypatch):
        monkeypatch.setattr(
            "app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: ["C_PRIVATE"]
        )
        client = FakeAsyncClient(
            get_handler=_by_url_suffix({"/conversations.history": {"ok": False, "error": "not_in_channel"}})
        )

        data = asyncio.run(SlackFetcher().fetch_with_client(client, SLACK_CREDENTIALS, 1, SINCE))

        assert data.events == []

    def test_token_level_channel_failure_raises_rather_than_looking_like_an_empty_channel(self, monkeypatch):
        """`not_in_channel` means only this one channel is unreadable -- skip it. `missing_scope`
        means the token itself is broken, so every remaining channel would fail identically; that
        must raise SourceUnavailable instead of silently completing as a successful empty fetch.
        """

        monkeypatch.setattr(
            "app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: ["C_PRIVATE"]
        )
        client = FakeAsyncClient(
            get_handler=_by_url_suffix({"/conversations.history": {"ok": False, "error": "missing_scope"}})
        )

        with pytest.raises(SourceUnavailable, match="missing_scope"):
            asyncio.run(SlackFetcher().fetch_with_client(client, SLACK_CREDENTIALS, 1, SINCE))

    def test_messages_from_other_users_are_not_recorded(self, monkeypatch):
        other_users_message = {**SLACK_MESSAGE, "user": "U09SOMEONEELSE", "ts": "1784799100.000000"}
        data, _ = self._fetch([SLACK_MESSAGE, other_users_message], monkeypatch)

        assert [event.external_id for event in data.events] == ["C123LOGLINE:1784799000.123456"]

    def test_missing_connected_user_id_skips_the_source_entirely(self, monkeypatch):
        """Without a known identity to filter on, over-collecting everyone's messages is worse than
        fetching nothing -- the source is skipped by default.
        """

        monkeypatch.setattr(
            "app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: ["C123LOGLINE"]
        )
        client = FakeAsyncClient(
            get_handler=_by_url_suffix({"/conversations.history": {"ok": True, "messages": [SLACK_MESSAGE]}})
        )
        no_identity = SourceCredentials(access_token="test-token", authed_user_id=None)

        data = asyncio.run(SlackFetcher().fetch_with_client(client, no_identity, 1, SINCE))

        assert data.events == []
        assert client.calls == []

    def test_conversation_discovery_uses_users_conversations_not_conversations_list(self, monkeypatch):
        """`conversations.list` enumerates the whole workspace's channels of the requested types,
        not just ones this user belongs to -- for a large workspace that means paging through
        thousands of irrelevant channels, which live testing showed trips Slack's rate limit.
        `users.conversations` is pre-scoped to membership, so it's the correct call here.
        """

        monkeypatch.setattr("app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: [])
        channel = {"id": "C1", "name": "general", "is_member": True}
        dm = {"id": "D1", "is_im": True, "user": "U09OTHER"}
        client = FakeAsyncClient(
            get_handler=lambda url, **kwargs: (
                _response({"ok": True, "channels": [channel, dm]})
                if url.endswith("/users.conversations")
                else _response({"ok": True, "messages": []})
            )
        )

        asyncio.run(SlackFetcher().fetch_with_client(client, SLACK_CREDENTIALS, 1, SINCE))

        assert not any(call.url.endswith("/conversations.list") for call in client.calls)
        history_channel_ids = {
            call.kwargs["params"]["channel"] for call in client.calls if call.url.endswith("/conversations.history")
        }
        assert history_channel_ids == {"C1", "D1"}

    def test_conversation_discovery_failure_raises_rather_than_silently_fetching_nothing(self, monkeypatch):
        """Slack reports a missing-scope token as HTTP 200 + `ok: false`, not an HTTP error --
        silently treating that as zero conversations would let a scope regression advance the
        high-water mark past a window that was never actually fetched.
        """

        monkeypatch.setattr("app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: [])
        client = FakeAsyncClient(
            get_handler=_by_url_suffix({"/users.conversations": {"ok": False, "error": "missing_scope"}})
        )

        with pytest.raises(SourceUnavailable, match="missing_scope"):
            asyncio.run(SlackFetcher().fetch_with_client(client, SLACK_CREDENTIALS, 1, SINCE))

    def test_history_pagination_follows_the_cursor_until_exhausted(self, monkeypatch):
        monkeypatch.setattr(
            "app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: ["C123LOGLINE"]
        )
        page_1 = {**SLACK_MESSAGE, "ts": "1784799000.000000"}
        page_2 = {**SLACK_MESSAGE, "ts": "1784799100.000000"}

        def handler(url, **kwargs):
            if kwargs.get("params", {}).get("cursor"):
                return _response({"ok": True, "messages": [page_2]})
            return _response({"ok": True, "messages": [page_1], "response_metadata": {"next_cursor": "abc"}})

        client = FakeAsyncClient(get_handler=handler)
        data = asyncio.run(SlackFetcher().fetch_with_client(client, SLACK_CREDENTIALS, 1, SINCE))

        history_calls = [call for call in client.calls if call.url.endswith("/conversations.history")]
        assert len(history_calls) == 2
        assert data.fetched_through_override is None
        assert {event.external_id for event in data.events} == {
            "C123LOGLINE:1784799000.000000",
            "C123LOGLINE:1784799100.000000",
        }

    def test_hitting_the_page_cap_without_exhausting_the_cursor_holds_the_high_water_mark(self, monkeypatch):
        monkeypatch.setattr(
            "app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: ["C123LOGLINE"]
        )
        message = {**SLACK_MESSAGE, "ts": "1784799000.000000"}
        client = FakeAsyncClient(
            get_handler=lambda url, **kwargs: _response(
                {"ok": True, "messages": [message], "response_metadata": {"next_cursor": "always-more"}}
            )
        )

        data = asyncio.run(SlackFetcher().fetch_with_client(client, SLACK_CREDENTIALS, 1, SINCE))

        assert data.fetched_through_override == datetime.fromtimestamp(1784799000.0, tz=timezone.utc)

    def test_standard_thread_replies_are_fetched_via_conversations_replies(self, monkeypatch):
        """conversations.history returns thread roots (with a reply_count) but never the replies
        themselves -- a standard (non-broadcast) reply from the connected user needs a separate
        conversations.replies call to surface at all.
        """

        monkeypatch.setattr(
            "app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: ["C123LOGLINE"]
        )
        root = {
            "type": "message",
            "user": "U09SOMEONEELSE",
            "text": "Anyone looked at the flaky test yet?",
            "ts": "1784799000.000000",
            "reply_count": 1,
        }
        reply = {
            "type": "message",
            "user": CONNECTED_SLACK_USER_ID,
            "text": "Yep, tracked it down to a timezone bug",
            "ts": "1784799500.000000",
            "thread_ts": "1784799000.000000",
        }

        def handler(url, **kwargs):
            if url.endswith("/conversations.history"):
                return _response({"ok": True, "messages": [root]})
            if url.endswith("/conversations.replies"):
                assert kwargs["params"]["ts"] == "1784799000.000000"
                return _response({"ok": True, "messages": [root, reply]})
            raise AssertionError(f"unexpected GET call: {url}")

        client = FakeAsyncClient(get_handler=handler)
        data = asyncio.run(SlackFetcher().fetch_with_client(client, SLACK_CREDENTIALS, 1, SINCE))

        assert [event.external_id for event in data.events] == ["C123LOGLINE:1784799500.000000"]


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
        client = FakeAsyncClient(get_handler=lambda url, **kwargs: _response({"items": events}))
        data = asyncio.run(CalendarFetcher().fetch_with_client(client, CREDENTIALS, 1, since))
        return data, client

    def test_summary_is_structural_and_description_is_the_agenda(self):
        data, _ = self._fetch([CALENDAR_MEETING])

        event = data.events[0]
        assert event.summary == "Phase 3 design review (2 attendees)"
        assert event.description == "Walk through the fetch-state schema before we build it."

    def test_remote_project_id_is_none_because_a_meeting_has_no_project(self):
        data, _ = self._fetch([CALENDAR_MEETING])

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
            "attendees": [{"email": "toheed.asghar@arbisoft.com", "self": True, "responseStatus": "declined"}],
        }
        data, _ = self._fetch([declined])

        assert data.events == []

    def test_time_bounds_are_rfc3339_with_a_trailing_z(self):
        since = datetime(2026, 7, 1, 12, 30, 45, 987654, tzinfo=timezone.utc)
        _, client = self._fetch([], since=since)

        params = client.calls[0].kwargs["params"]
        assert params["timeMin"] == "2026-07-01T12:30:45Z"
        assert params["timeMax"].endswith("Z")
        assert "." not in params["timeMax"]
        assert params["singleEvents"] == "true"

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
        assert {event.external_id for event in data.events} == {"standup_20260721T090000Z", "standup_20260722T090000Z"}

    def test_pagination_follows_next_page_token_until_exhausted(self):
        page_1_event = {**CALENDAR_MEETING, "id": "evt-page1"}
        page_2_event = {**CALENDAR_MEETING, "id": "evt-page2"}

        def handler(url, **kwargs):
            if kwargs.get("params", {}).get("pageToken"):
                return _response({"items": [page_2_event]})
            return _response({"items": [page_1_event], "nextPageToken": "abc"})

        client = FakeAsyncClient(get_handler=handler)
        data = asyncio.run(CalendarFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert {event.external_id for event in data.events} == {"evt-page1", "evt-page2"}
        assert len(client.calls) == 2

    def test_a_response_under_the_page_size_does_not_paginate_further(self):
        _, client = self._fetch([CALENDAR_MEETING])

        assert len(client.calls) == 1

    def test_events_beyond_max_events_per_source_hold_the_high_water_mark(self):
        base = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
        many_events = [
            {
                "id": f"evt-{i}",
                "summary": f"Meeting {i}",
                "start": {"dateTime": (base + timedelta(minutes=i)).isoformat()},
            }
            for i in range(MAX_EVENTS_PER_SOURCE + 5)
        ]
        data, _ = self._fetch(many_events)

        assert len(data.events) == MAX_EVENTS_PER_SOURCE
        assert data.fetched_through_override == base + timedelta(minutes=MAX_EVENTS_PER_SOURCE - 1)

    def test_hitting_the_page_cap_holds_the_high_water_mark_to_the_last_raw_event_seen(self):
        """A raw fetch cut off by CALENDAR_MAX_PAGES is known-incomplete -- advancing the watermark
        to `now` would skip whatever came after the last page actually requested, even though far
        fewer than MAX_EVENTS_PER_SOURCE events survived filtering.
        """

        base = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
        event = {"id": "evt-repeat", "summary": "Standup", "start": {"dateTime": base.isoformat()}}
        client = FakeAsyncClient(
            get_handler=lambda url, **kwargs: _response({"items": [event], "nextPageToken": "always-more"})
        )

        data = asyncio.run(CalendarFetcher().fetch_with_client(client, CREDENTIALS, 1, SINCE))

        assert len(client.calls) == CALENDAR_MAX_PAGES
        assert data.fetched_through_override == base


# --- Cross-source -----------------------------------------------------------


class TestEveryFetcherProducesSchemaShapedEvents:
    """Whatever the source, the output must slot straight into `remote_events` -- non-null
    source/event_type/external_id/occurred_at, and a raw_data dict (the column is NOT NULL).
    """

    @pytest.mark.parametrize("fetcher_name", ["github", "jira", "slack", "calendar"])
    def test_required_columns_are_populated(self, fetcher_name, monkeypatch):
        if fetcher_name == "github":
            monkeypatch.setattr(
                "app.remote_fetch.sources.github.get_user_github_repos", lambda user_id: ["Toheed/logline"]
            )
            client = FakeAsyncClient(
                get_handler=_by_url_suffix({"/commits": [GITHUB_COMMIT], "/pulls": [GITHUB_PULL_REQUEST]})
            )
            fetcher = GitHubFetcher()
            credentials = CREDENTIALS
        elif fetcher_name == "jira":
            monkeypatch.setattr(
                "app.remote_fetch.sources.jira.get_mapped_remote_project_ids", lambda user_id, source: []
            )
            monkeypatch.setattr(
                "app.remote_fetch.sources.jira.get_cached_jira_cloud_id", lambda user_id: "cloud-id-123"
            )
            client = FakeAsyncClient(post_handler=lambda url, **kwargs: _response({"issues": [JIRA_ISSUE]}))
            fetcher = JiraFetcher()
            credentials = CREDENTIALS
        elif fetcher_name == "slack":
            monkeypatch.setattr(
                "app.remote_fetch.sources.slack.get_mapped_remote_project_ids", lambda user_id, source: ["C123LOGLINE"]
            )
            client = FakeAsyncClient(
                get_handler=_by_url_suffix({"/conversations.history": {"ok": True, "messages": [SLACK_MESSAGE]}})
            )
            fetcher = SlackFetcher()
            credentials = SLACK_CREDENTIALS
        else:
            client = FakeAsyncClient(get_handler=lambda url, **kwargs: _response({"items": [CALENDAR_MEETING]}))
            fetcher = CalendarFetcher()
            credentials = CREDENTIALS

        data = asyncio.run(fetcher.fetch_with_client(client, credentials, 1, SINCE))

        assert data.events, f"{fetcher_name} produced no events"
        for event in data.events:
            assert event.source == fetcher_name
            assert event.event_type
            assert event.external_id
            assert event.occurred_at.tzinfo is not None
            assert isinstance(event.raw_data, dict) and event.raw_data
