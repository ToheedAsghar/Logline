"""
Regression tests for the date-grounding gap found during live Jira
re-validation: in 2 of 5 live runs, the agent reasoned about "today" using
either a hallucinated date or without ever confirming the real current date
via calendar__get-current-time, producing a false "no activity found"
conclusion in one case despite real evidence existing for the actual day.

SYSTEM_PROMPT now has an explicit step 0 requiring calendar__get-current-time
before any date-scoped query. Since a prompt is advisory, not enforced,
Toolbelt.dispatch also carries a code-level backstop: it tracks whether
calendar__get-current-time has been called yet this run, and logs a warning
if a Jira/GitHub/Calendar tool call carrying a literal date arrives before
that. This can only flag "date used before grounding happened" -- there's no
independent clock to prove the date is wrong -- so it warns rather than
rejects, matching this file's existing auto-correct-don't-raise style (see
_validate_github_date_syntax).

These tests mock the MCP client and drive Toolbelt.dispatch directly. They
run offline and fast -- no network access, no real LLM call, no MCP server.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from app.agent.llm.base import ToolCall
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import Toolbelt, _contains_literal_date


def _mock_call_tool_result() -> MagicMock:
    result = MagicMock()
    result.content = []
    return result


def _toolbelt_with_sources(*sources: str) -> tuple[Toolbelt, dict[str, AsyncMock]]:
    toolbelt = Toolbelt(user_id=1)
    sessions = {}
    for source in sources:
        mock_session = AsyncMock()
        mock_session.call_tool.return_value = _mock_call_tool_result()
        toolbelt._sessions[source] = mock_session
        sessions[source] = mock_session
    return toolbelt, sessions


class TestContainsLiteralDate:
    def test_detects_iso_date_in_arguments(self):
        assert _contains_literal_date({"jql": "updated >= '2026-07-07'"})

    def test_ignores_relative_jql_functions(self):
        assert not _contains_literal_date({"jql": "assignee = currentUser() AND updated >= startOfDay()"})

    def test_ignores_arguments_with_no_dates(self):
        assert not _contains_literal_date({"limit": 50, "fields": "summary,status"})


class TestDateGroundingBackstop:
    """Toolbelt.dispatch must track whether calendar__get-current-time has
    been called this run, and warn (not block) when a date-scoped call to
    Jira/GitHub/Calendar arrives with a literal date before that."""

    def test_new_toolbelt_has_not_established_current_time(self):
        toolbelt = Toolbelt(user_id=1)
        assert toolbelt._current_time_established is False

    def test_calling_get_current_time_establishes_grounding(self):
        toolbelt, sessions = _toolbelt_with_sources("calendar")
        toolbelt._mcp_tool_index["calendar__get-current-time"] = ("calendar", "get-current-time")
        tool_call = ToolCall(id="1", name="calendar__get-current-time", arguments={})

        asyncio.run(toolbelt.dispatch(tool_call))

        assert toolbelt._current_time_established is True

    def test_warns_when_jira_search_uses_literal_date_before_grounding(self, caplog):
        toolbelt, sessions = _toolbelt_with_sources("jira")
        toolbelt._mcp_tool_index["jira__jira_search"] = ("jira", "jira_search")
        tool_call = ToolCall(
            id="1",
            name="jira__jira_search",
            arguments={"jql": "updated >= '2024-01-19' AND updated < '2024-01-20'"},
        )

        with caplog.at_level(logging.WARNING):
            asyncio.run(toolbelt.dispatch(tool_call))

        assert any("date-grounding" in record.message for record in caplog.records)

    def test_no_warning_once_current_time_has_been_established(self, caplog):
        toolbelt, sessions = _toolbelt_with_sources("calendar", "jira")
        toolbelt._mcp_tool_index["calendar__get-current-time"] = ("calendar", "get-current-time")
        toolbelt._mcp_tool_index["jira__jira_search"] = ("jira", "jira_search")

        asyncio.run(toolbelt.dispatch(ToolCall(id="1", name="calendar__get-current-time", arguments={})))
        with caplog.at_level(logging.WARNING):
            asyncio.run(
                toolbelt.dispatch(
                    ToolCall(
                        id="2",
                        name="jira__jira_search",
                        arguments={"jql": "updated >= '2026-07-07'"},
                    )
                )
            )

        assert not any("date-grounding" in record.message for record in caplog.records)

    def test_no_warning_when_jira_query_uses_relative_jql_only(self, caplog):
        toolbelt, sessions = _toolbelt_with_sources("jira")
        toolbelt._mcp_tool_index["jira__jira_search"] = ("jira", "jira_search")
        tool_call = ToolCall(
            id="1",
            name="jira__jira_search",
            arguments={"jql": "assignee = currentUser() AND updated >= startOfDay()"},
        )

        with caplog.at_level(logging.WARNING):
            asyncio.run(toolbelt.dispatch(tool_call))

        assert not any("date-grounding" in record.message for record in caplog.records)

    def test_warns_for_github_committer_date_before_grounding(self, caplog):
        toolbelt, sessions = _toolbelt_with_sources("github")
        toolbelt._mcp_tool_index["github__search_commits"] = ("github", "search_commits")
        tool_call = ToolCall(
            id="1",
            name="github__search_commits",
            arguments={"query": "repo:owner/name committer-date:2024-01-19..2024-01-19"},
        )

        with caplog.at_level(logging.WARNING):
            asyncio.run(toolbelt.dispatch(tool_call))

        assert any("date-grounding" in record.message for record in caplog.records)

    def test_warns_for_calendar_list_events_before_grounding(self, caplog):
        toolbelt, sessions = _toolbelt_with_sources("calendar")
        toolbelt._mcp_tool_index["calendar__list-events"] = ("calendar", "list-events")
        tool_call = ToolCall(
            id="1",
            name="calendar__list-events",
            arguments={"timeMin": "2024-01-19T00:00:00Z", "timeMax": "2024-01-19T23:59:59Z"},
        )

        with caplog.at_level(logging.WARNING):
            asyncio.run(toolbelt.dispatch(tool_call))

        assert any("date-grounding" in record.message for record in caplog.records)

    def test_dispatch_does_not_raise_or_block_the_call(self, caplog):
        """The backstop only warns -- it must never reject the tool call itself."""
        toolbelt, sessions = _toolbelt_with_sources("jira")
        toolbelt._mcp_tool_index["jira__jira_search"] = ("jira", "jira_search")
        tool_call = ToolCall(
            id="1",
            name="jira__jira_search",
            arguments={"jql": "updated >= '2024-01-19'"},
        )

        result = asyncio.run(toolbelt.dispatch(tool_call))

        sessions["jira"].call_tool.assert_awaited_once()
        assert "error" not in result if isinstance(result, dict) else True


class TestSystemPromptDateGroundingStep:
    """The prompt's step 0 must exist and be unambiguous about ordering."""

    def test_system_prompt_requires_get_current_time_before_relative_dates(self):
        assert "calendar__get-current-time" in SYSTEM_PROMPT
        assert '"today"' in SYSTEM_PROMPT or "\"today\"" in SYSTEM_PROMPT

    def test_system_prompt_step_zero_precedes_get_existing_events_step(self):
        step_zero_index = SYSTEM_PROMPT.index("0. Before interpreting any relative date reference")
        step_one_index = SYSTEM_PROMPT.index("1. Call get_existing_events first")
        assert step_zero_index < step_one_index

    def test_system_prompt_names_jira_github_calendar_as_date_scoped_examples(self):
        assert "JQL date/range" in SYSTEM_PROMPT
        assert "committer-date:.." in SYSTEM_PROMPT
        assert "list-events timeMin/timeMax" in SYSTEM_PROMPT
