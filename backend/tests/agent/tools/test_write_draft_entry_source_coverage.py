"""
Regression tests for the "checked every connected source" requirement on
write_draft_entry (Toolbelt.dispatch in app/agent/toolbelt.py).

Root cause: the agent could call write_draft_entry having never attempted
github/slack/jira/calendar, because flag_gap only answers "is there
uncovered time in the events table I already wrote to" -- a different
question from "did I check every connected source" -- and the model
conflated the two. As with DATE_GROUNDING, a prompt-only fix isn't reliable
on its own, so Toolbelt now tracks which MCP sources have had at least one
tool call attempted this run (success or failure both count -- this is an
"attempted" requirement, not a "found something" requirement) and rejects
write_draft_entry with an error naming whichever connected source(s) are
still missing, until all of them have been touched.

The requirement is scoped to sources that actually connected this run
(Toolbelt._sessions), not a hardcoded four -- a source that failed to
connect (e.g. a missing credential) registers no tool the model could ever
call, so requiring it would deadlock the agent forever.

These tests drive Toolbelt.dispatch directly with mocked MCP sessions and a
mocked write_draft_entry DB session. Offline and fast -- no real LLM/MCP
calls, mirroring the pattern in test_date_grounding.py and
test_agent_runner_created_entry_id.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import app.agent.tools.write_draft_entry as write_draft_entry_module
from app.agent.llm.base import ToolCall
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import Toolbelt

ALL_SOURCES = ("github", "slack", "jira", "calendar")

WRITE_DRAFT_ENTRY_CALL = ToolCall(
    id="draft-1",
    name="write_draft_entry",
    arguments={
        "format": "project_log",
        "content": {"text": "Worked on the API today."},
        "work_date": "2026-07-22",
    },
)


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


def _register_mcp_tool(toolbelt: Toolbelt, source: str, native_name: str = "noop") -> str:
    qualified_name = f"{source}__{native_name}"
    toolbelt._mcp_tool_index[qualified_name] = (source, native_name)
    return qualified_name


def _attempt(toolbelt: Toolbelt, source: str) -> None:
    qualified_name = _register_mcp_tool(toolbelt, source)
    asyncio.run(toolbelt.dispatch(ToolCall(id=source, name=qualified_name, arguments={})))


def _fake_session_cm(fake_db: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value = fake_db
    cm.__exit__.return_value = False
    return cm


def _mock_write_draft_entry_db(monkeypatch, entry_id: int) -> MagicMock:
    fake_db = MagicMock()

    def fake_refresh(entry):
        entry.id = entry_id

    fake_db.refresh.side_effect = fake_refresh
    monkeypatch.setattr(write_draft_entry_module, "SessionLocal", lambda: _fake_session_cm(fake_db))
    return fake_db


class TestAttemptedSourcesTracking:
    def test_new_toolbelt_has_attempted_no_sources(self):
        toolbelt = Toolbelt(user_id=1)
        assert toolbelt._attempted_sources == set()

    def test_dispatching_an_mcp_tool_call_marks_its_source_attempted(self):
        toolbelt, _sessions = _toolbelt_with_sources("jira")
        _attempt(toolbelt, "jira")

        assert toolbelt._attempted_sources == {"jira"}

    def test_attempt_is_recorded_even_when_the_mcp_call_raises(self):
        """Success or failure both count as an attempt -- this requires the
        agent to have tried a source, not that the source found anything."""
        toolbelt, sessions = _toolbelt_with_sources("slack")
        qualified_name = _register_mcp_tool(toolbelt, "slack")
        sessions["slack"].call_tool.side_effect = RuntimeError("boom")

        result = asyncio.run(toolbelt.dispatch(ToolCall(id="1", name=qualified_name, arguments={})))

        assert "error" in result
        assert toolbelt._attempted_sources == {"slack"}


class TestWriteDraftEntryBlockedUntilAllConnectedSourcesAttempted:
    def test_rejected_when_no_source_has_been_attempted(self):
        toolbelt, _sessions = _toolbelt_with_sources(*ALL_SOURCES)

        result = asyncio.run(toolbelt.dispatch(WRITE_DRAFT_ENTRY_CALL))

        assert "error" in result
        for source in ALL_SOURCES:
            assert source in result["error"]

    def test_rejected_and_names_only_the_sources_still_missing(self):
        toolbelt, _sessions = _toolbelt_with_sources(*ALL_SOURCES)
        _attempt(toolbelt, "github")

        result = asyncio.run(toolbelt.dispatch(WRITE_DRAFT_ENTRY_CALL))

        assert "error" in result
        assert "github" not in result["error"]
        for source in ("slack", "jira", "calendar"):
            assert source in result["error"]

    def test_rejection_does_not_write_anything_to_the_database(self, monkeypatch):
        fake_db = _mock_write_draft_entry_db(monkeypatch, entry_id=123)
        toolbelt, _sessions = _toolbelt_with_sources(*ALL_SOURCES)

        asyncio.run(toolbelt.dispatch(WRITE_DRAFT_ENTRY_CALL))

        fake_db.add.assert_not_called()


class TestWriteDraftEntrySucceedsOnceAllConnectedSourcesAttempted:
    def test_succeeds_regardless_of_whether_each_source_found_anything(self, monkeypatch):
        fake_db = _mock_write_draft_entry_db(monkeypatch, entry_id=777)
        toolbelt, _sessions = _toolbelt_with_sources(*ALL_SOURCES)
        for source in ALL_SOURCES:
            _attempt(toolbelt, source)

        result = asyncio.run(toolbelt.dispatch(WRITE_DRAFT_ENTRY_CALL))

        assert result == {"success": True, "status": "created", "entry_id": 777}
        assert fake_db.add.call_count == 2  # Entry row, then its ai_draft EntryVersion row

    def test_only_requires_sources_that_actually_connected(self, monkeypatch):
        """A source with no live MCP connection this run (e.g. a missing
        credential) has no tool the model could call to satisfy the
        requirement, so it must not be required -- only what's in
        self._sessions is."""
        fake_db = _mock_write_draft_entry_db(monkeypatch, entry_id=999)
        toolbelt, _sessions = _toolbelt_with_sources("github", "slack")  # jira/calendar never connected
        _attempt(toolbelt, "github")
        _attempt(toolbelt, "slack")

        result = asyncio.run(toolbelt.dispatch(WRITE_DRAFT_ENTRY_CALL))

        assert result == {"success": True, "status": "created", "entry_id": 999}
        assert fake_db.add.call_count == 2  # Entry row, then its ai_draft EntryVersion row

    def test_succeeds_when_no_mcp_sources_connected_at_all(self, monkeypatch):
        """Mirrors the dev/test setup in test_agent_runner_created_entry_id.py
        where every MCP source is left unconnected -- must not deadlock."""
        fake_db = _mock_write_draft_entry_db(monkeypatch, entry_id=888)
        toolbelt = Toolbelt(user_id=1)

        result = asyncio.run(toolbelt.dispatch(WRITE_DRAFT_ENTRY_CALL))

        assert result == {"success": True, "status": "created", "entry_id": 888}
        assert fake_db.add.call_count == 2  # Entry row, then its ai_draft EntryVersion row


class TestSystemPromptDraftEntrySourceCoverageGuidance:
    """The prompt layer must state the requirement too (efficiency/guidance
    layer, same pattern as DATE_GROUNDING) -- but the tests above are what
    actually guarantee it, since a prompt alone is advisory."""

    def test_system_prompt_states_every_connected_source_requirement(self):
        assert "every connected source" in SYSTEM_PROMPT
        assert "write_draft_entry" in SYSTEM_PROMPT

    def test_system_prompt_says_the_requirement_is_enforced_in_code(self):
        assert "enforced in code" in SYSTEM_PROMPT
