"""
Regression tests for Slack channel-lookup behavior currently only verified by
running `scripts/manual_test_agent_runner.py` by hand:

1. `slack_find_channel` (Toolbelt.dispatch's wrapper around the raw
   `slack_list_channels` MCP tool) must paginate through the *entire* channel
   list to find a channel by name, and report a clean "not found" once pages
   are exhausted -- never raise or hang.
2. When `slack_get_channel_history` returns `'not_in_channel'` for a guessed
   channel, the agent should fall back to `slack_list_my_channels` instead of
   treating Slack as a dead end.

Note on adaptation, mirroring test_github_search_scoping.py: per
backend/CLAUDE.md ("no hardcoded pipeline"), `Toolbelt.dispatch` has no
`if result == 'not_in_channel': retry` branch -- deciding to retry with
slack_list_my_channels is left entirely to the agent's own reasoning
(SYSTEM_PROMPT + the SLACK_LIST_MY_CHANNELS_TOOL description it reads), not
scripted in Python. So behavior #2 is tested by pinning that prompt/tool-
description contract, plus a dispatch-level test proving the fallback tool
itself works correctly when called -- i.e. it is not a dead end -- and a test
pinning that dispatch passes a `not_in_channel` result through unmodified
(no silent Python-side handling to mask). Behavior #1 (pagination) is real
code in `_iter_all_slack_channels` / `_find_slack_channel_id`, dispatched via
the `slack_find_channel` tool name, so it's tested directly against mocked
`slack_list_channels` pages.

These tests mock the Slack MCP session the same way
test_github_search_scoping.py mocks the GitHub one -- no real Slack calls, no
npx/@modelcontextprotocol/server-slack process spawned.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.llm.base import AgentResponse, LLMProvider, ToolCall
from app.agent.runner import run_agent
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import SLACK_LIST_MY_CHANNELS_TOOL, Toolbelt
import app.agent.runner as runner_module


def _slack_page_result(channels: list[dict], next_cursor: str | None = None) -> MagicMock:
    payload = {
        "ok": True,
        "channels": channels,
        "response_metadata": {"next_cursor": next_cursor} if next_cursor else {},
    }
    result = MagicMock()
    result.content = [MagicMock(text=json.dumps(payload))]
    return result


def _slack_toolbelt() -> tuple[Toolbelt, AsyncMock]:
    toolbelt = Toolbelt(user_id=1)
    mock_session = AsyncMock()
    toolbelt._sessions["slack"] = mock_session
    return toolbelt, mock_session


class TestSlackFindChannelPagination:
    """slack_find_channel must page through slack_list_channels, not just check page one."""

    def test_finds_channel_on_first_page(self):
        toolbelt, mock_session = _slack_toolbelt()
        mock_session.call_tool.return_value = _slack_page_result(
            [{"id": "C1", "name": "general", "is_member": True}]
        )
        tool_call = ToolCall(id="1", name="slack_find_channel", arguments={"name": "general"})

        result = asyncio.run(toolbelt.dispatch(tool_call))

        assert result == {"found": True, "channel_id": "C1"}

    def test_paginates_through_multiple_pages_to_find_channel(self):
        toolbelt, mock_session = _slack_toolbelt()
        page_1 = _slack_page_result(
            [{"id": "C1", "name": "random", "is_member": False}], next_cursor="cursor-2"
        )
        page_2 = _slack_page_result([{"id": "C2", "name": "logline_mcp_test", "is_member": True}])
        mock_session.call_tool.side_effect = [page_1, page_2]
        tool_call = ToolCall(id="1", name="slack_find_channel", arguments={"name": "logline_mcp_test"})

        result = asyncio.run(toolbelt.dispatch(tool_call))

        assert result == {"found": True, "channel_id": "C2"}
        assert mock_session.call_tool.call_count == 2
        first_args = mock_session.call_tool.call_args_list[0].kwargs["arguments"]
        second_args = mock_session.call_tool.call_args_list[1].kwargs["arguments"]
        assert "cursor" not in first_args
        assert second_args["cursor"] == "cursor-2"

    def test_returns_not_found_after_exhausting_all_pages(self):
        toolbelt, mock_session = _slack_toolbelt()
        page_1 = _slack_page_result(
            [{"id": "C1", "name": "random", "is_member": False}], next_cursor="cursor-2"
        )
        page_2 = _slack_page_result([{"id": "C2", "name": "other", "is_member": True}])  # no next_cursor
        mock_session.call_tool.side_effect = [page_1, page_2]
        tool_call = ToolCall(id="1", name="slack_find_channel", arguments={"name": "does-not-exist"})

        result = asyncio.run(toolbelt.dispatch(tool_call))

        assert result == {"found": False}
        assert mock_session.call_tool.call_count == 2

    def test_missing_slack_session_reports_error_instead_of_crashing(self):
        toolbelt = Toolbelt(user_id=1)  # no "slack" session connected
        tool_call = ToolCall(id="1", name="slack_find_channel", arguments={"name": "general"})

        result = asyncio.run(toolbelt.dispatch(tool_call))

        assert result == {"error": "Slack MCP server is not connected."}


class TestSlackNotInChannelFallback:
    """
    slack_get_channel_history returning 'not_in_channel' must not be a dead
    end. There's no Python branch that intercepts this and auto-retries (see
    module docstring) -- the retry decision is the agent's, driven by
    SYSTEM_PROMPT and the SLACK_LIST_MY_CHANNELS_TOOL description. So this
    pins: (a) that contract text, (b) that dispatch passes the raw
    'not_in_channel' result through unmodified rather than swallowing it, and
    (c) that the fallback tool the agent is told to call actually works.
    """

    def test_system_prompt_instructs_fallback_on_not_in_channel(self):
        assert "slack_get_channel_history returns 'not_in_channel'" in SYSTEM_PROMPT
        assert "slack_list_my_channels to see the real channels available to you" in SYSTEM_PROMPT
        assert "instead of giving up on Slack" in SYSTEM_PROMPT

    def test_tool_description_instructs_fallback_on_not_in_channel(self):
        assert (
            "Call this if slack_get_channel_history returns 'not_in_channel' for a "
            "channel you guessed or found by name" in SLACK_LIST_MY_CHANNELS_TOOL.description
        )

    def test_dispatch_passes_not_in_channel_result_through_unmodified(self, monkeypatch):
        """Pins that dispatch doesn't hide or retry the error itself -- the agent must."""
        toolbelt, mock_session = _slack_toolbelt()
        toolbelt._mcp_tool_index["slack__slack_get_channel_history"] = ("slack", "slack_get_channel_history")
        not_in_channel_result = MagicMock()
        not_in_channel_result.content = [MagicMock(text=json.dumps({"ok": False, "error": "not_in_channel"}))]
        mock_session.call_tool.return_value = not_in_channel_result
        tool_call = ToolCall(
            id="1",
            name="slack__slack_get_channel_history",
            arguments={"channel_id": "C_GUESSED"},
        )

        result = asyncio.run(toolbelt.dispatch(tool_call))

        assert result == {"ok": False, "error": "not_in_channel"}

    def test_dispatch_slack_list_my_channels_returns_real_member_channels(self):
        """When the agent does fall back, the wrapper must return usable channels, not another error."""
        toolbelt, mock_session = _slack_toolbelt()
        mock_session.call_tool.return_value = _slack_page_result(
            [
                {"id": "C1", "name": "random", "is_member": False},
                {"id": "C2", "name": "logline_mcp_test", "is_member": True},
            ]
        )
        tool_call = ToolCall(id="1", name="slack_list_my_channels", arguments={})

        result = asyncio.run(toolbelt.dispatch(tool_call))

        assert result == {"channels": [{"id": "C2", "name": "logline_mcp_test"}]}


class _ScriptedSlackFallbackProvider(LLMProvider):
    """Stands in for an LLM that follows SYSTEM_PROMPT's not_in_channel
    fallback instruction. It is *reactive* -- it inspects the actual tool
    result content in `messages` to decide its next move, rather than
    replaying a fixed call sequence blind to input -- so a test built on top
    of it actually exercises `run_agent`'s message-threading (does the tool
    result really make it back to the "model" in a form it can act on),
    not just a hardcoded list of expected calls.

    This cannot prove a *real* LLM will choose to fall back -- that's
    inherently untestable offline. What it proves is that the real
    `runner.py` + `toolbelt.py` code, unmodified, correctly turns "the model
    asked for slack_list_my_channels" into an actual dispatched call and a
    result the loop can continue from -- closing the gap left by
    TestSlackNotInChannelFallback's prompt-text-only assertions above.
    """

    def __init__(self) -> None:
        self.requested_tool_names: list[str] = []

    async def run_turn(self, messages, tools) -> AgentResponse:
        last = messages[-1]

        if last.role == "user":
            call = ToolCall(
                id="1",
                name="slack__slack_get_channel_history",
                arguments={"channel_id": "C_GUESSED"},
            )
            self.requested_tool_names.append(call.name)
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        if last.role == "tool" and "not_in_channel" in (last.content or ""):
            call = ToolCall(id="2", name="slack_list_my_channels", arguments={})
            self.requested_tool_names.append(call.name)
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        return AgentResponse(
            text="Checked Slack via the real channel from the fallback list.",
            tool_calls=[],
            is_final=True,
        )


class TestFullAgentRunNotInChannelFallback:
    """
    Full-loop behavioral test: mocks the LLM (reactively, see
    `_ScriptedSlackFallbackProvider`) and the Slack MCP session, then drives
    the actual `run_agent` loop end to end -- not an isolated
    `Toolbelt.dispatch` call -- to prove the not_in_channel ->
    slack_list_my_channels fallback really happens in the assembled agent,
    not just as prompt text asserted in isolation.
    """

    def test_not_in_channel_result_leads_to_slack_list_my_channels_call(self, monkeypatch):
        mock_session = AsyncMock()

        async def fake_call_tool(name, arguments=None, **_kwargs):
            if name == "slack_list_channels":
                return _slack_page_result(
                    [
                        {"id": "C1", "name": "random", "is_member": False},
                        {"id": "C2", "name": "logline_mcp_test", "is_member": True},
                    ]
                )
            if name == "slack_get_channel_history":
                result = MagicMock()
                result.content = [MagicMock(text=json.dumps({"ok": False, "error": "not_in_channel"}))]
                return result
            raise AssertionError(f"unexpected slack tool call: {name}")

        mock_session.call_tool.side_effect = fake_call_tool

        async def fake_connect_mcp_source(self, source, build_params):
            if source == "slack":
                self._sessions["slack"] = mock_session
                self._mcp_tool_index["slack__slack_get_channel_history"] = (
                    "slack",
                    "slack_get_channel_history",
                )
            # github/calendar/jira intentionally left unconnected -- this test
            # only exercises the Slack fallback path, and real connections
            # would require real credentials/subprocesses.

        monkeypatch.setattr(Toolbelt, "_connect_mcp_source", fake_connect_mcp_source)

        provider = _ScriptedSlackFallbackProvider()
        monkeypatch.setattr(runner_module, "get_llm_provider", lambda: provider)

        result = asyncio.run(run_agent(user_id=1, task="Summarize my Slack activity today."))

        assert provider.requested_tool_names == [
            "slack__slack_get_channel_history",
            "slack_list_my_channels",
        ]
        called_native_names = [call.args[0] for call in mock_session.call_tool.call_args_list]
        assert called_native_names == [
            "slack_list_channels",  # __aenter__ resolving the write-restricted allowed channel
            "slack_get_channel_history",  # round 1: the guessed channel, returns not_in_channel
            "slack_list_channels",  # round 2: the fallback, triggered by the not_in_channel result
        ]
        assert result.response_text == "Checked Slack via the real channel from the fallback list."
        assert result.created_entry_id is None
