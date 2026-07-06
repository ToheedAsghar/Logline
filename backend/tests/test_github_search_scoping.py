"""
Regression tests for two bugs fixed in this session:

1. search_commits (and search_issues / search_pull_requests) must be scoped
   to a specific repo via `repo:owner/name`. Without this, queries either
   silently return nothing or match across unrelated repos.

2. Date-scoped commit search must use `committer-date:YYYY-MM-DD..YYYY-MM-DD`.
   The earlier `since:`/`until:` qualifiers are invalid for search_commits and
   fail SILENTLY (zero results, no error) -- which looks identical to "no
   commits today" and is easy to miss.

Note on adaptation from the original draft: this codebase has no pure
`build_*_search_query()` helpers -- per backend/CLAUDE.md, tool-call ordering
and query construction are left entirely to the agent's own reasoning, not
hardcoded in Python (`Toolbelt` just dispatches whatever query the model
built). The two bugs are actually fixed in two different places:

- The repo-scoping *contract* is enforced in code: `Toolbelt.dispatch` only
  auto-scopes `search_commits`/`search_issues`/`search_pull_requests` calls
  when the user has an explicit repo list configured
  (`get_user_github_repos`); otherwise it passes the query through unchanged
  and relies on the agent having called `search_repositories` first, per
  `SYSTEM_PROMPT`.
- The committer-date syntax fix is *entirely* a prompt-engineering fix --
  there is no Python function that builds that query string, so it's tested
  by asserting on `SYSTEM_PROMPT`'s content instead of a return value.

These tests mock the GitHub MCP client and assert on the `query=` kwarg
`Toolbelt.dispatch` passes to `session.call_tool`, plus the `SYSTEM_PROMPT`
text and `get_user_github_repos`'s DB-read contract. They run offline and
fast -- no network access or GitHub token required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.llm.base import ToolCall
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import Toolbelt, _query_has_repo_scope, get_user_github_repos
import app.agent.toolbelt as toolbelt_module


def _mock_call_tool_result() -> MagicMock:
    result = MagicMock()
    result.content = []
    return result


def _github_toolbelt(monkeypatch: pytest.MonkeyPatch, stored_repos):
    toolbelt = Toolbelt(user_id=1)
    mock_session = AsyncMock()
    mock_session.call_tool.return_value = _mock_call_tool_result()
    toolbelt._sessions["github"] = mock_session
    toolbelt._mcp_tool_index["github__search_commits"] = ("github", "search_commits")
    toolbelt._mcp_tool_index["github__search_issues"] = ("github", "search_issues")
    toolbelt._mcp_tool_index["github__search_pull_requests"] = ("github", "search_pull_requests")
    monkeypatch.setattr(toolbelt_module, "get_user_github_repos", lambda user_id: stored_repos)
    return toolbelt, mock_session


class TestRepoScoping:
    """Every commit/issue/PR search call must end up scoped to a repo."""

    @pytest.mark.parametrize(
        "query",
        ["repo:owner/name foo", "org:owner foo", "user:owner foo"],
    )
    def test_query_has_repo_scope_accepts_any_valid_qualifier(self, query):
        assert _query_has_repo_scope(query)

    def test_query_has_repo_scope_rejects_unscoped_query(self):
        assert not _query_has_repo_scope("committer-date:2026-07-06..2026-07-06")

    def test_dispatch_auto_scopes_unscoped_query_when_repos_configured(self, monkeypatch):
        toolbelt, mock_session = _github_toolbelt(monkeypatch, ["ToheedAsghar/Logline"])
        tool_call = ToolCall(
            id="1",
            name="github__search_commits",
            arguments={"query": "committer-date:2026-07-06..2026-07-06"},
        )

        asyncio.run(toolbelt.dispatch(tool_call))

        sent_query = mock_session.call_tool.call_args.kwargs["arguments"]["query"]
        assert _query_has_repo_scope(sent_query)
        assert "repo:ToheedAsghar/Logline" in sent_query

    def test_dispatch_leaves_already_scoped_query_untouched(self, monkeypatch):
        toolbelt, mock_session = _github_toolbelt(monkeypatch, ["ToheedAsghar/Logline"])
        original_query = "repo:other/repo committer-date:2026-07-06..2026-07-06"
        tool_call = ToolCall(id="1", name="github__search_commits", arguments={"query": original_query})

        asyncio.run(toolbelt.dispatch(tool_call))

        sent_query = mock_session.call_tool.call_args.kwargs["arguments"]["query"]
        assert sent_query == original_query

    def test_dispatch_passes_through_unscoped_query_when_no_repos_configured(self, monkeypatch):
        """
        With no stored repo list, `Toolbelt.dispatch` has nothing to auto-scope
        with -- it relies entirely on the agent having called
        search_repositories first (enforced via SYSTEM_PROMPT, not code). This
        pins that current, intentional contract rather than inventing a raise
        that doesn't exist in toolbelt.py.
        """
        toolbelt, mock_session = _github_toolbelt(monkeypatch, None)
        original_query = "committer-date:2026-07-06..2026-07-06"
        tool_call = ToolCall(id="1", name="github__search_commits", arguments={"query": original_query})

        asyncio.run(toolbelt.dispatch(tool_call))

        sent_query = mock_session.call_tool.call_args.kwargs["arguments"]["query"]
        assert sent_query == original_query


class TestCommitterDateSyntax:
    """
    Date-scoped commit search must use committer-date:, never since:/until:.
    There's no query-builder function to call here -- this behavior is driven
    entirely by SYSTEM_PROMPT instructing the agent, so we assert on the
    prompt text itself.
    """

    def test_system_prompt_documents_committer_date_range_syntax(self):
        assert "committer-date:YYYY-MM-DD..YYYY-MM-DD" in SYSTEM_PROMPT

    def test_system_prompt_explicitly_flags_since_until_as_invalid_for_commits(self):
        assert "search_commits has no `since`/`until` qualifier" in SYSTEM_PROMPT

    def test_system_prompt_requires_search_repositories_before_scoped_search(self):
        assert "Never call one of those three with an unscoped query" in SYSTEM_PROMPT
        assert "call search_repositories" in SYSTEM_PROMPT


class TestGetUserGithubRepos:
    """get_user_github_repos must distinguish 'not configured' from 'configured but empty'."""

    def _patch_session(self, monkeypatch: pytest.MonkeyPatch, integration):
        fake_query = MagicMock()
        fake_query.filter.return_value.first.return_value = integration
        fake_db = MagicMock()
        fake_db.query.return_value = fake_query
        fake_session_cm = MagicMock()
        fake_session_cm.__enter__.return_value = fake_db
        fake_session_cm.__exit__.return_value = False
        monkeypatch.setattr(toolbelt_module, "SessionLocal", lambda: fake_session_cm)

    def test_returns_none_when_no_integration_row(self, monkeypatch):
        self._patch_session(monkeypatch, integration=None)
        assert get_user_github_repos(user_id=1) is None

    def test_returns_none_when_metadata_has_no_repos_key(self, monkeypatch):
        integration = MagicMock()
        integration.integration_metadata = {}
        self._patch_session(monkeypatch, integration=integration)
        assert get_user_github_repos(user_id=1) is None

    def test_returns_stored_list_when_configured(self, monkeypatch):
        integration = MagicMock()
        integration.integration_metadata = {"repos": ["ToheedAsghar/Logline"]}
        self._patch_session(monkeypatch, integration=integration)
        assert get_user_github_repos(user_id=1) == ["ToheedAsghar/Logline"]


class TestCalendarAccountParam:
    """Calendar MCP calls must never forward an `account` argument (see fix commit)."""

    def test_dispatch_strips_account_param(self, monkeypatch):
        toolbelt = Toolbelt(user_id=1)
        mock_session = AsyncMock()
        mock_session.call_tool.return_value = _mock_call_tool_result()
        toolbelt._sessions["calendar"] = mock_session
        toolbelt._mcp_tool_index["calendar__list-events"] = ("calendar", "list-events")
        tool_call = ToolCall(
            id="1",
            name="calendar__list-events",
            arguments={"account": "work", "calendarId": "primary"},
        )

        asyncio.run(toolbelt.dispatch(tool_call))

        sent_arguments = mock_session.call_tool.call_args.kwargs["arguments"]
        assert "account" not in sent_arguments
        assert sent_arguments["calendarId"] == "primary"
