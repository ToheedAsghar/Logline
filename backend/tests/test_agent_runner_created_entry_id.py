"""
Regression tests for `run_agent`'s return shape (app/agent/runner.py).

`run_agent` used to return a bare response string; the frontend then had to
make a separate follow-up `useEntries()` request, sorted by newest, just to
guess which entry the agent had just created via `write_draft_entry` during
the run. That's an unnecessary extra round-trip and fragile if entry ids
ever stop being sequential integers.

`run_agent` now returns an `AgentRunResult(response_text, created_entry_id)`
-- `created_entry_id` is the id `write_draft_entry` produced during this run
(captured straight from its dispatch result, no new DB query), or None if
`write_draft_entry` was never called.

Both tests below drive the real `run_agent` + `Toolbelt.dispatch` +
`write_draft_entry` loop end to end (mocking only the LLM provider and
`write_draft_entry`'s DB session), mirroring the full-loop pattern in
test_calendar_location_exclusion.py. No real LLM/MCP calls are made.
"""

import asyncio
from unittest.mock import MagicMock

import app.agent.runner as runner_module
import app.agent.tools.write_draft_entry as write_draft_entry_module
from app.agent.llm.base import AgentResponse, LLMProvider, ToolCall
from app.agent.runner import run_agent
from app.agent.toolbelt import Toolbelt


def _fake_session_cm(fake_db: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value = fake_db
    cm.__exit__.return_value = False
    return cm


async def _fake_connect_mcp_source(self, source, build_params):
    # No MCP sources are needed for these tests -- write_draft_entry is a
    # custom tool, not an MCP one, so every source is left unconnected.
    return


class _ScriptedWriteDraftEntryProvider(LLMProvider):
    """Requests `write_draft_entry` once, then finalizes on the next turn."""

    def __init__(self) -> None:
        self.requested_tool_names: list[str] = []

    async def run_turn(self, messages, tools) -> AgentResponse:
        last = messages[-1]

        if last.role == "user":
            call = ToolCall(
                id="1",
                name="write_draft_entry",
                arguments={
                    "format": "project_log",
                    "content": {"text": "Worked on the API today."},
                    "work_date": "2026-07-22",
                },
            )
            self.requested_tool_names.append(call.name)
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        return AgentResponse(text="Draft entry created.", tool_calls=[], is_final=True)


class _ScriptedNoDraftProvider(LLMProvider):
    """A plain evidence-gathering run that never calls write_draft_entry."""

    async def run_turn(self, messages, tools) -> AgentResponse:
        return AgentResponse(
            text="Gathered evidence; no draft synthesized.", tool_calls=[], is_final=True
        )


class TestRunAgentReturnsCreatedEntryId:
    def test_created_entry_id_is_populated_when_write_draft_entry_is_called(self, monkeypatch):
        fake_db = MagicMock()

        def fake_refresh(entry):
            entry.id = 555

        fake_db.refresh.side_effect = fake_refresh
        monkeypatch.setattr(
            write_draft_entry_module, "SessionLocal", lambda: _fake_session_cm(fake_db)
        )
        monkeypatch.setattr(Toolbelt, "_connect_mcp_source", _fake_connect_mcp_source)

        provider = _ScriptedWriteDraftEntryProvider()
        monkeypatch.setattr(runner_module, "get_llm_provider", lambda: provider)

        result = asyncio.run(run_agent(user_id=1, task="Log today's work as a project log."))

        assert provider.requested_tool_names == ["write_draft_entry"]
        assert fake_db.add.call_count == 1
        assert result.response_text == "Draft entry created."
        assert result.created_entry_id == 555

    def test_created_entry_id_is_none_when_write_draft_entry_is_never_called(self, monkeypatch):
        monkeypatch.setattr(Toolbelt, "_connect_mcp_source", _fake_connect_mcp_source)

        provider = _ScriptedNoDraftProvider()
        monkeypatch.setattr(runner_module, "get_llm_provider", lambda: provider)

        result = asyncio.run(run_agent(user_id=1, task="What did I work on today?"))

        assert result.response_text == "Gathered evidence; no draft synthesized."
        assert result.created_entry_id is None
