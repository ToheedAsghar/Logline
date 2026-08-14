"""Fetches commits and pull requests from GitHub and normalizes them into events.

Supports fetching explicitly configured user repositories or discovering activity
authored by the authenticated user.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from mcp import ClientSession

from app.integrations.config import get_user_github_repos
from app.remote_fetch.base import FetchedEvent, SourceFetchData, SourceFetcher
from app.remote_fetch.constants import MAX_EVENTS_PER_SOURCE
from app.remote_fetch.mcp.connection import mcp_result_to_json
from app.remote_fetch.parsing import first_non_empty_string, parse_iso_datetime, split_commit_message

logger = logging.getLogger(__name__)

SOURCE = "github"
EVENT_TYPE_COMMIT = "commit"
EVENT_TYPE_PULL_REQUEST = "pull_request"

GITHUB_PER_PAGE = 100
GITHUB_MAX_PAGES = 5


def _as_list(payload: Any, *keys: str) -> list[dict[str, Any]]:
    """Extract a list of dictionary items from a list or wrapped response payload."""

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _combine_override(a: Optional[datetime], b: Optional[datetime]) -> Optional[datetime]:
    """Return the earlier of two datetime high-water mark overrides."""

    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _commit_event(commit: dict[str, Any], repo: Optional[str]) -> Optional[FetchedEvent]:
    """Build a commit FetchedEvent from a GitHub commit payload.

    Returns None if the payload lacks a valid SHA or timestamp.
    """

    sha = first_non_empty_string(commit.get("sha"), commit.get("id"))
    if sha is None:
        return None

    inner = commit.get("commit") if isinstance(commit.get("commit"), dict) else {}
    committer = inner.get("committer") if isinstance(inner.get("committer"), dict) else {}
    author = inner.get("author") if isinstance(inner.get("author"), dict) else {}

    occurred_at = parse_iso_datetime(committer.get("date")) or parse_iso_datetime(author.get("date"))
    if occurred_at is None:
        return None

    repository = commit.get("repository") if isinstance(commit.get("repository"), dict) else {}
    full_name = first_non_empty_string(repository.get("full_name"), repo)

    subject, body = split_commit_message(inner.get("message"))
    author_login = None
    if isinstance(commit.get("author"), dict):
        author_login = first_non_empty_string(commit["author"].get("login"))

    return FetchedEvent(
        source=SOURCE,
        event_type=EVENT_TYPE_COMMIT,
        external_id=sha,
        occurred_at=occurred_at,
        summary=subject,
        description=body,
        remote_project_id=full_name,
        match_keys={
            "repo": full_name,
            "sha": sha,
            "author": author_login or first_non_empty_string(author.get("name")),
        },
        raw_data=commit,
    )


def _pull_request_event(pull_request: dict[str, Any], repo: Optional[str]) -> Optional[FetchedEvent]:
    """Build a pull request FetchedEvent from a GitHub PR payload.

    Returns None if the payload lacks a PR number or timestamp.
    """

    number = pull_request.get("number")
    if not isinstance(number, int):
        return None

    occurred_at = parse_iso_datetime(pull_request.get("updated_at")) or parse_iso_datetime(
        pull_request.get("created_at")
    )
    if occurred_at is None:
        return None

    repository = pull_request.get("repository") if isinstance(pull_request.get("repository"), dict) else {}
    full_name = first_non_empty_string(repository.get("full_name"), repo)

    base = pull_request.get("base") if isinstance(pull_request.get("base"), dict) else {}
    head = pull_request.get("head") if isinstance(pull_request.get("head"), dict) else {}

    state = first_non_empty_string(pull_request.get("state")) or "unknown"
    if pull_request.get("merged_at"):
        state = "merged"
    title = first_non_empty_string(pull_request.get("title"))

    external_id = f"{full_name}#{number}" if full_name else f"pull_request#{number}"

    return FetchedEvent(
        source=SOURCE,
        event_type=EVENT_TYPE_PULL_REQUEST,
        external_id=external_id,
        occurred_at=occurred_at,
        summary=f"PR #{number} [{state}] {title}" if title else f"PR #{number} [{state}]",
        description=first_non_empty_string(pull_request.get("body")),
        remote_project_id=full_name,
        match_keys={
            "repo": full_name,
            "number": number,
            "state": state,
            "base_branch": first_non_empty_string(base.get("ref")),
            "head_branch": first_non_empty_string(head.get("ref")),
        },
        raw_data=pull_request,
    )


class GitHubFetcher(SourceFetcher):
    source = SOURCE

    async def fetch_with_session(
        self, session: ClientSession, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        repos = (
            self.remote_fetch_config.github_repos
            if self.remote_fetch_config is not None
            else get_user_github_repos(user_id)
        )
        if repos:
            events, override = await self._fetch_configured_repos(session, repos, since)
        else:
            login = await self._get_login(session)
            if login is None:
                logger.warning("github: no configured repos and get_me returned no login; nothing to fetch")
                return SourceFetchData(events=[])
            events, override = await self._fetch_by_author(session, login, since)

        events.sort(key=lambda event: event.occurred_at)
        if len(events) > MAX_EVENTS_PER_SOURCE:
            cutoff = events[MAX_EVENTS_PER_SOURCE - 1].occurred_at
            override = _combine_override(override, cutoff)
            events = events[:MAX_EVENTS_PER_SOURCE]

        return SourceFetchData(events=events, fetched_through_override=override)

    async def _get_login(self, session: ClientSession) -> Optional[str]:
        result = await session.call_tool("get_me", arguments={})
        payload = mcp_result_to_json(result)
        if isinstance(payload, dict):
            return first_non_empty_string(payload.get("login"))
        return None

    async def _fetch_configured_repos(
        self, session: ClientSession, repos: list[str], since: Optional[datetime]
    ) -> tuple[list[FetchedEvent], Optional[datetime]]:
        events: list[FetchedEvent] = []
        override: Optional[datetime] = None
        for repo in repos:
            owner, _, name = repo.partition("/")
            if not owner or not name:
                logger.warning("github: skipping malformed repo identifier %r (want 'owner/repo')", repo)
                continue
            (commit_events, commit_override), (pr_events, pr_override) = await asyncio.gather(
                self._fetch_repo_commits(session, owner, name, since),
                self._fetch_repo_pull_requests(session, owner, name, since),
            )
            events.extend(commit_events)
            events.extend(pr_events)
            override = _combine_override(override, commit_override)
            override = _combine_override(override, pr_override)
        return events, override

    async def _fetch_repo_commits(
        self, session: ClientSession, owner: str, name: str, since: Optional[datetime]
    ) -> tuple[list[FetchedEvent], Optional[datetime]]:
        """Fetch commits for a repository up to GITHUB_MAX_PAGES.

        Returns matching commit events and a high-water mark override if truncated.
        """

        repo = f"{owner}/{name}"
        events: list[FetchedEvent] = []
        truncated = False

        for page in range(1, GITHUB_MAX_PAGES + 1):
            arguments: dict[str, Any] = {
                "owner": owner,
                "repo": name,
                "perPage": GITHUB_PER_PAGE,
                "page": page,
            }
            if since is not None:
                arguments["since"] = since.isoformat()

            result = await session.call_tool("list_commits", arguments=arguments)
            items = _as_list(mcp_result_to_json(result), "commits", "items")
            if not items:
                break

            for commit in items:
                event = _commit_event(commit, repo)
                if event is not None:
                    events.append(event)

            if len(items) < GITHUB_PER_PAGE:
                break
            if page == GITHUB_MAX_PAGES:
                truncated = True

        override = None
        if truncated and events:
            events.sort(key=lambda event: event.occurred_at)
            override = events[0].occurred_at

        return events, override

    async def _fetch_repo_pull_requests(
        self, session: ClientSession, owner: str, name: str, since: Optional[datetime]
    ) -> tuple[list[FetchedEvent], Optional[datetime]]:
        """Fetch pull requests for a repository updated since the given timestamp."""

        repo = f"{owner}/{name}"
        events: list[FetchedEvent] = []
        truncated = False

        for page in range(1, GITHUB_MAX_PAGES + 1):
            result = await session.call_tool(
                "list_pull_requests",
                arguments={
                    "owner": owner,
                    "repo": name,
                    "state": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "perPage": GITHUB_PER_PAGE,
                    "page": page,
                },
            )
            items = _as_list(mcp_result_to_json(result), "pull_requests", "items")
            if not items:
                break

            for item in items:
                event = _pull_request_event(item, repo)
                if event is None:
                    continue
                if since is not None and event.occurred_at <= since:
                    return events, None
                events.append(event)

            if len(items) < GITHUB_PER_PAGE:
                break
            if page == GITHUB_MAX_PAGES:
                truncated = True

        override = None
        if truncated and events:
            events.sort(key=lambda event: event.occurred_at)
            override = events[0].occurred_at
        return events, override

    async def _search_paginated(
        self,
        session: ClientSession,
        tool_name: str,
        query: str,
        sort: str,
        list_keys: tuple[str, ...],
        build_event: Callable[[dict[str, Any]], Optional[FetchedEvent]],
    ) -> tuple[list[FetchedEvent], bool]:
        """Execute a paginated GitHub search tool call up to GITHUB_MAX_PAGES.

        Returns a tuple of parsed events and a boolean indicating if truncation occurred.
        """

        events: list[FetchedEvent] = []
        truncated = False

        for page in range(1, GITHUB_MAX_PAGES + 1):
            result = await session.call_tool(
                tool_name,
                arguments={
                    "query": query,
                    "sort": sort,
                    "order": "desc",
                    "perPage": GITHUB_PER_PAGE,
                    "page": page,
                },
            )
            items = _as_list(mcp_result_to_json(result), *list_keys)
            if not items:
                break

            for item in items:
                event = build_event(item)
                if event is not None:
                    events.append(event)

            if len(items) < GITHUB_PER_PAGE:
                break
            if page == GITHUB_MAX_PAGES:
                truncated = True

        return events, truncated

    async def _fetch_by_author(
        self, session: ClientSession, login: str, since: Optional[datetime]
    ) -> tuple[list[FetchedEvent], Optional[datetime]]:
        """Discover and fetch commits and pull requests authored by a specific user across repos."""

        date_qualifier = f" committer-date:>={since.date().isoformat()}" if since else ""
        commit_events, commits_truncated = await self._search_paginated(
            session,
            "search_commits",
            query=f"author:{login}{date_qualifier}",
            sort="committer-date",
            list_keys=("items", "commits"),
            build_event=lambda item: _commit_event(item, None),
        )

        pr_date_qualifier = f" updated:>={since.date().isoformat()}" if since else ""
        pr_events, prs_truncated = await self._search_paginated(
            session,
            "search_pull_requests",
            query=f"author:{login}{pr_date_qualifier}",
            sort="updated",
            list_keys=("items", "pull_requests"),
            build_event=lambda item: _pull_request_event(item, _repo_from_search_item(item)),
        )

        events = commit_events + pr_events

        truncated_events = (commit_events if commits_truncated else []) + (
            pr_events if prs_truncated else []
        )
        override = min((event.occurred_at for event in truncated_events), default=None)

        return events, override


def _repo_from_search_item(item: dict[str, Any]) -> Optional[str]:
    """Extract the owner/repo string from a GitHub search result item."""

    repository = item.get("repository")
    if isinstance(repository, dict):
        full_name = first_non_empty_string(repository.get("full_name"))
        if full_name:
            return full_name

    repository_url = first_non_empty_string(item.get("repository_url"))
    if repository_url and "/repos/" in repository_url:
        candidate = repository_url.split("/repos/", 1)[1].strip("/")
        if candidate.count("/") == 1:
            return candidate
    return None
