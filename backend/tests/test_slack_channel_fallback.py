"""
Regression tests for `get_slack_channel_activity`, the composite Slack tool in
app/agent/toolbelt.py that replaced a three-step flow
(slack_find_channel -> slack_list_my_channels fallback ->
slack__slack_get_channel_history).

Root cause this replaced: Toolbelt.dispatch only marked a source "attempted"
(self._attempted_sources) from its generic MCP-tool-index branch, which only
step 3 of the old flow (the native slack_get_channel_history call) went
through. Steps 1/2 (slack_find_channel, slack_list_my_channels) were separate
early-return branches that never reached that code. If the agent's Slack
exploration only went through steps 1/2 -- e.g. channel search came back
empty -- Slack never got marked attempted, and write_draft_entry kept
rejecting indefinitely until MAX_TOOL_ROUNDS ran out with no draft produced.
Confirmed as the root cause of a failed live "Generate Standup" test.

Collapsing to one composite tool call fixes this structurally (one call site
marks "slack" attempted, unconditionally, regardless of outcome) and also
saves round trips: each round costs a full LLM inference cycle on top of the
actual Slack API call.

These tests mock the Slack MCP session the same way
test_github_search_scoping.py mocks the GitHub one -- no real Slack calls, no
npx/@modelcontextprotocol/server-slack process spawned.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import app.agent.runner as runner_module
from app.agent.llm.base import AgentResponse, LLMProvider, ToolCall
from app.agent.runner import run_agent
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import GET_SLACK_CHANNEL_ACTIVITY_TOOL, Toolbelt


def _slack_page_result(channels: list[dict], next_cursor: str | None = None) -> MagicMock:
    payload = {
        "ok": True,
        "channels": channels,
        "response_metadata": {"next_cursor": next_cursor} if next_cursor else {},
    }
    result = MagicMock()
    result.content = [MagicMock(text=json.dumps(payload))]
    return result


def _slack_history_result(messages: list[dict]) -> MagicMock:
    result = MagicMock()
    result.content = [MagicMock(text=json.dumps({"ok": True, "messages": messages}))]
    return result


def _not_in_channel_result() -> MagicMock:
    result = MagicMock()
    result.content = [MagicMock(text=json.dumps({"ok": False, "error": "not_in_channel"}))]
    return result


def _slack_toolbelt() -> tuple[Toolbelt, AsyncMock]:
    toolbelt = Toolbelt(user_id=1)
    mock_session = AsyncMock()
    toolbelt._sessions["slack"] = mock_session
    return toolbelt, mock_session


def _activity_call(name: str) -> ToolCall:
    return ToolCall(id="1", name="get_slack_channel_activity", arguments={"name": name})


class TestChannelFoundAndReadInOneCall:
    def test_finds_channel_on_first_page_and_reads_history(self):
        toolbelt, mock_session = _slack_toolbelt()
        mock_session.call_tool.side_effect = [
            _slack_page_result([{"id": "C1", "name": "general", "is_member": True}]),
            _slack_history_result([{"ts": "111.222", "text": "hello"}]),
        ]

        result = asyncio.run(toolbelt.dispatch(_activity_call("general")))

        assert result == {
            "found": True,
            "channel_id": "C1",
            "history": {"ok": True, "messages": [{"ts": "111.222", "text": "hello"}]},
        }
        called_names = [call.args[0] for call in mock_session.call_tool.call_args_list]
        assert called_names == ["slack_list_channels", "slack_get_channel_history"]
        history_args = mock_session.call_tool.call_args_list[1].kwargs["arguments"]
        assert history_args == {"channel_id": "C1"}
        assert toolbelt._attempted_sources == {"slack"}

    def test_finds_channel_via_pagination_and_reads_history(self):
        toolbelt, mock_session = _slack_toolbelt()
        page_1 = _slack_page_result(
            [{"id": "C1", "name": "random", "is_member": False}], next_cursor="cursor-2"
        )
        page_2 = _slack_page_result([{"id": "C2", "name": "logline_mcp_test", "is_member": True}])
        mock_session.call_tool.side_effect = [
            page_1,
            page_2,
            _slack_history_result([{"ts": "999.001", "text": "hi"}]),
        ]

        result = asyncio.run(toolbelt.dispatch(_activity_call("logline_mcp_test")))

        assert result["found"] is True
        assert result["channel_id"] == "C2"
        assert mock_session.call_tool.call_count == 3
        assert toolbelt._attempted_sources == {"slack"}


class TestChannelNotFoundFallsBackToMemberChannels:
    def test_channel_not_found_by_name_but_bot_has_other_channels(self):
        toolbelt, mock_session = _slack_toolbelt()
        # Same channel list is returned for both the (failed) name search and
        # the fallback member-channel listing -- get_slack_channel_activity
        # re-pages internally for the fallback, it doesn't reuse results.
        mock_session.call_tool.return_value = _slack_page_result(
            [
                {"id": "C1", "name": "random", "is_member": False},
                {"id": "C2", "name": "logline_mcp_test", "is_member": True},
            ]
        )

        result = asyncio.run(toolbelt.dispatch(_activity_call("does-not-exist")))

        assert result["found"] is False
        assert result["requested_name"] == "does-not-exist"
        assert result["member_channels"] == [{"id": "C2", "name": "logline_mcp_test"}]
        assert "does-not-exist" in result["message"]
        # slack_get_channel_history is never reached -- no channel id was found.
        called_names = [call.args[0] for call in mock_session.call_tool.call_args_list]
        assert "slack_get_channel_history" not in called_names
        assert toolbelt._attempted_sources == {"slack"}

    def test_channel_genuinely_not_found_at_all(self):
        """Bot has zero accessible channels -- fallback list is simply empty,
        not an error, so the agent can still act on the result."""
        toolbelt, mock_session = _slack_toolbelt()
        mock_session.call_tool.return_value = _slack_page_result(
            [{"id": "C1", "name": "random", "is_member": False}]
        )

        result = asyncio.run(toolbelt.dispatch(_activity_call("does-not-exist")))

        assert result == {
            "found": False,
            "requested_name": "does-not-exist",
            "member_channels": [],
            "message": (
                "No accessible channel named 'does-not-exist' found. Pick a real "
                "channel from member_channels and call get_slack_channel_activity "
                "again with its name."
            ),
        }
        assert toolbelt._attempted_sources == {"slack"}

    def test_channel_found_by_name_but_bot_not_a_member_falls_back(self):
        """A name can match a real channel the pagination sees, but the bot
        might not actually be a member of it -- slack_get_channel_history then
        returns not_in_channel, which must also trigger the member_channels
        fallback rather than surfacing a bare error."""
        toolbelt, mock_session = _slack_toolbelt()

        async def fake_call_tool(name, arguments=None, **_kwargs):
            if name == "slack_list_channels":
                return _slack_page_result(
                    [
                        {"id": "C1", "name": "private-guess", "is_member": False},
                        {"id": "C2", "name": "logline_mcp_test", "is_member": True},
                    ]
                )
            if name == "slack_get_channel_history":
                return _not_in_channel_result()
            raise AssertionError(f"unexpected slack tool call: {name}")

        mock_session.call_tool.side_effect = fake_call_tool

        result = asyncio.run(toolbelt.dispatch(_activity_call("private-guess")))

        assert result["found"] is False
        assert result["member_channels"] == [{"id": "C2", "name": "logline_mcp_test"}]
        assert toolbelt._attempted_sources == {"slack"}


class TestMissingSlackSession:
    def test_missing_slack_session_reports_error_but_still_marks_attempted(self):
        toolbelt = Toolbelt(user_id=1)  # no "slack" session connected

        result = asyncio.run(toolbelt.dispatch(_activity_call("general")))

        assert result == {"error": "Slack MCP server is not connected."}
        # Marked unconditionally from this single call site regardless of
        # outcome -- see the tracking-bug fix this test file documents above.
        assert toolbelt._attempted_sources == {"slack"}


class TestToolDefinitionAndPromptDescribeSingleToolFlow:
    def test_tool_description_documents_fallback_and_attempted_semantics(self):
        assert GET_SLACK_CHANNEL_ACTIVITY_TOOL.name == "get_slack_channel_activity"
        assert "member_channels" in GET_SLACK_CHANNEL_ACTIVITY_TOOL.description
        assert "not_in_channel" in GET_SLACK_CHANNEL_ACTIVITY_TOOL.description

    def test_system_prompt_describes_single_tool_flow(self):
        assert "get_slack_channel_activity" in SYSTEM_PROMPT
        assert "member_channels" in SYSTEM_PROMPT
        assert "slack_find_channel" not in SYSTEM_PROMPT
        assert "slack_list_my_channels" not in SYSTEM_PROMPT


class _ScriptedSlackFallbackProvider(LLMProvider):
    """Stands in for an LLM that follows SYSTEM_PROMPT's member_channels
    fallback instruction. It is *reactive* -- it inspects the actual tool
    result content in `messages` to decide its next move, rather than
    replaying a fixed call sequence blind to input -- so a test built on top
    of it actually exercises `run_agent`'s message-threading (does the tool
    result really make it back to the "model" in a form it can act on), not
    just a hardcoded list of expected calls.

    This cannot prove a *real* LLM will choose to fall back -- that's
    inherently untestable offline. What it proves is that the real
    `runner.py` + `toolbelt.py` code, unmodified, correctly turns "the model
    asked for get_slack_channel_activity" into an actual dispatched call and
    a result the loop can continue from.
    """

    def __init__(self) -> None:
        self.requested_names: list[str] = []

    async def run_turn(self, messages, tools) -> AgentResponse:
        last = messages[-1]

        if last.role == "user":
            self.requested_names.append("wrong-guess")
            call = ToolCall(id="1", name="get_slack_channel_activity", arguments={"name": "wrong-guess"})
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        if last.role == "tool" and "\"found\": false" in (last.content or ""):
            real_name = json.loads(last.content)["member_channels"][0]["name"]
            self.requested_names.append(real_name)
            call = ToolCall(id="2", name="get_slack_channel_activity", arguments={"name": real_name})
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        return AgentResponse(
            text="Checked Slack via the real channel from the fallback list.",
            tool_calls=[],
            is_final=True,
        )


class TestFullAgentRunMemberChannelsFallback:
    """Full-loop behavioral test: mocks the LLM (reactively, see
    `_ScriptedSlackFallbackProvider`) and the Slack MCP session, then drives
    the actual `run_agent` loop end to end -- not an isolated
    `Toolbelt.dispatch` call -- to prove the not-found -> member_channels
    fallback really happens in the assembled agent, and that it costs exactly
    one dispatched tool call per attempt (no separate find/list round trips).
    """

    def test_not_found_result_leads_to_retry_with_a_real_channel_name(self, monkeypatch):
        mock_session = AsyncMock()

        async def fake_call_tool(name, arguments=None, **_kwargs):
            if name == "slack_list_channels":
                return _slack_page_result(
                    [
                        {"id": "C1", "name": "wrong-guess", "is_member": False},
                        {"id": "C2", "name": "logline_mcp_test", "is_member": True},
                    ]
                )
            if name == "slack_get_channel_history":
                # "wrong-guess" (C1) resolves to a real channel id, but the
                # bot isn't a member of it; "logline_mcp_test" (C2) succeeds.
                if arguments["channel_id"] == "C1":
                    return _not_in_channel_result()
                return _slack_history_result([{"ts": "1.0", "text": "hi"}])
            raise AssertionError(f"unexpected slack tool call: {name}")

        mock_session.call_tool.side_effect = fake_call_tool

        async def fake_connect_mcp_source(self, source, build_params):
            if source == "slack":
                self._sessions["slack"] = mock_session
            # github/calendar/jira intentionally left unconnected -- this test
            # only exercises the Slack fallback path, and real connections
            # would require real credentials/subprocesses.

        monkeypatch.setattr(Toolbelt, "_connect_mcp_source", fake_connect_mcp_source)

        provider = _ScriptedSlackFallbackProvider()
        monkeypatch.setattr(runner_module, "get_llm_provider", lambda: provider)

        result = asyncio.run(run_agent(user_id=1, task="Summarize my Slack activity today."))

        assert provider.requested_names == ["wrong-guess", "logline_mcp_test"]
        assert result.response_text == "Checked Slack via the real channel from the fallback list."
        assert result.created_entry_id is None
