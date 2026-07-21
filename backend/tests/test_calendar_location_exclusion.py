"""
Regression tests for calendar working-location handling currently only
verified by running `scripts/manual_test_agent_runner.py` by hand:

1. A working-location entry (e.g. "Home", "Office") must never be written via
   write_event as proven work evidence.
2. A working-location entry must not count toward gap detection (flag_gap's
   output must be the same whether or not one is present).
3. A real calendar event (actual title, attendees) must still be processed
   as evidence -- confirming the exclusion isn't over-broad.

Note on adaptation, mirroring test_github_search_scoping.py: per
backend/CLAUDE.md, this codebase has no per-source branching logic anywhere
("Never add per-source tables or per-source branching logic" -- see the
generic event shape section) and no hardcoded pipeline ("no
correlation_engine.py... an LLM agent... decides entirely on its own"). There
is, correspondingly, no Python function anywhere (not in `Toolbelt.dispatch`,
not in `write_event`, not in `flag_gap`) that inspects a calendar event and
decides "this is a working-location entry, skip it." `write_event` and
`flag_gap` are fully source-agnostic: they write/count whatever they're
given. The exclusion is entirely a SYSTEM_PROMPT instruction to the agent
that decides which events are worth recording in the first place.

So these tests are split the same way the committer-date fix was tested:
- A dispatch-level test (mocking the Calendar MCP session, like
  TestCalendarAccountParam already does) pins that raw `list-events` results
  -- location entries mixed with real ones -- pass through
  `Toolbelt.dispatch` completely unfiltered. This is the *reason* prompt-side
  exclusion is necessary: nothing upstream removes them.
- write_event/flag_gap tests (mocking their DB session, like
  TestGetUserGithubRepos does) confirm both functions are genuinely
  source-agnostic -- they don't special-case "Home"/"Office" metadata, which
  is exactly why the agent, not the code, must be the one to skip them.
- SYSTEM_PROMPT assertions pin the actual exclusion contract: skip
  write_event, skip gap-detection weight, but still treat real
  title+attendees events as evidence.

No real Calendar MCP calls are made in these tests.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.agent.runner as runner_module
import app.agent.tools.flag_gap as flag_gap_module
import app.agent.tools.write_event as write_event_module
from app.agent.llm.base import AgentResponse, LLMProvider, ToolCall
from app.agent.runner import run_agent
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import Toolbelt
from app.agent.tools.flag_gap import flag_gap
from app.agent.tools.write_event import write_event

WORKING_LOCATION_EVENT = {
    "id": "evt-home",
    "summary": "Home",
    "eventType": "workingLocation",
    "start": {"date": "2026-07-06"},
}

REAL_EVENT = {
    "id": "evt-standup",
    "summary": "Team Standup",
    "attendees": [{"email": "toheed@arbisoft.com"}, {"email": "teammate@arbisoft.com"}],
    "start": {"dateTime": "2026-07-06T09:00:00Z"},
    "end": {"dateTime": "2026-07-06T09:15:00Z"},
}


def _mock_call_tool_result(payload: dict) -> MagicMock:
    result = MagicMock()
    result.content = [MagicMock(text=json.dumps(payload))]
    return result


class TestCalendarDispatchDoesNotFilterLocationEntries:
    """
    Pins the current, intentional contract: Toolbelt.dispatch does no
    source-specific filtering of calendar results (see module docstring) --
    it's a pure pass-through to whatever the Calendar MCP server returns.
    This is *why* the SYSTEM_PROMPT-level exclusion below is load-bearing.
    """

    def test_dispatch_passes_through_location_entries_unfiltered(self, monkeypatch):
        toolbelt = Toolbelt(user_id=1)
        mock_session = AsyncMock()
        mock_session.call_tool.return_value = _mock_call_tool_result(
            {"events": [WORKING_LOCATION_EVENT, REAL_EVENT]}
        )
        toolbelt._sessions["calendar"] = mock_session
        toolbelt._mcp_tool_index["calendar__list-events"] = ("calendar", "list-events")
        tool_call = ToolCall(
            id="1", name="calendar__list-events", arguments={"calendarId": "primary"}
        )

        result = asyncio.run(toolbelt.dispatch(tool_call))

        assert result == {"events": [WORKING_LOCATION_EVENT, REAL_EVENT]}


class TestWriteEventAndFlagGapAreSourceAgnostic:
    """
    write_event and flag_gap don't know what a "working location" is -- they
    have no per-source branching (per backend/CLAUDE.md). This confirms that
    fact directly, which is why the exclusion has to happen before either is
    ever called, not inside them.
    """

    def test_write_event_has_no_location_awareness_and_would_write_anything_given_to_it(self, monkeypatch):
        fake_db = MagicMock()
        fake_session_cm = MagicMock()
        fake_session_cm.__enter__.return_value = fake_db
        fake_session_cm.__exit__.return_value = False
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: fake_session_cm)

        write_event(
            user_id=1,
            source="calendar",
            type="workingLocation",
            timestamp="2026-07-06T00:00:00",
            metadata={"summary": "Home"},
            confidence="proven",
        )

        assert fake_db.add.called
        written_event = fake_db.add.call_args.args[0]
        assert written_event.type == "workingLocation"
        assert written_event.confidence.value == "proven"

    def test_flag_gap_counts_any_event_row_regardless_of_type(self, monkeypatch):
        fake_query = MagicMock()
        fake_query.filter.return_value.count.return_value = 1
        fake_db = MagicMock()
        fake_db.query.return_value = fake_query
        fake_session_cm = MagicMock()
        fake_session_cm.__enter__.return_value = fake_db
        fake_session_cm.__exit__.return_value = False
        monkeypatch.setattr(flag_gap_module, "SessionLocal", lambda: fake_session_cm)

        result = flag_gap(
            user_id=1,
            start_time="2026-07-06T00:00:00",
            end_time="2026-07-06T23:59:59",
        )

        assert result["is_gap"] is False
        assert result["event_count"] == 1


class TestSystemPromptExcludesWorkingLocationFromWriteEvent:
    def test_system_prompt_identifies_working_location_entries(self):
        assert 'Working-location entries (e.g. "Home", "Office") are metadata about' in SYSTEM_PROMPT

    def test_system_prompt_forbids_writing_location_entries_as_evidence(self):
        assert "Never write_event them as work evidence" in SYSTEM_PROMPT


class TestSystemPromptExcludesWorkingLocationFromGapDetection:
    def test_system_prompt_forbids_treating_location_entries_as_gaps(self):
        assert "never treat their lack of detail as a gap" in SYSTEM_PROMPT

    def test_system_prompt_excludes_location_entries_from_confidence_tiering(self):
        assert "for confidence-tiering purposes" in SYSTEM_PROMPT


class TestSystemPromptStillRequiresRealEventsAsEvidence:
    def test_system_prompt_still_counts_real_meetings_as_evidence(self):
        assert (
            "actual title and attendees count as calendar-sourced work evidence" in SYSTEM_PROMPT
        )


class _ScriptedCalendarExclusionProvider(LLMProvider):
    """Stands in for an LLM that correctly follows SYSTEM_PROMPT's
    working-location exclusion rule. It inspects the actual mixed event list
    returned by the mocked Calendar MCP call and applies the same skip rule
    the prompt asks the real model to apply (skip eventType ==
    "workingLocation"), then requests write_event only for what's left,
    followed by flag_gap -- reacting to real tool-result content and
    `tool_call_id`s threaded through `messages`, not replaying a fixed
    script blind to input.

    This cannot prove a *real* LLM will make this choice -- that's
    inherently untestable offline (SYSTEM_PROMPT's wording is covered
    separately, above). What it proves is that the real `runner.py` +
    `toolbelt.py` + `write_event.py` + `flag_gap.py` code, unmodified,
    correctly turns "the model chose to skip the Home entry" into a real
    DB write (or lack thereof) end to end -- closing the gap left by
    testing `write_event`/`Toolbelt.dispatch` in isolation.
    """

    def __init__(self) -> None:
        self.requested_tool_names: list[str] = []

    async def run_turn(self, messages, tools) -> AgentResponse:
        last = messages[-1]

        if last.role == "user":
            call = ToolCall(id="1", name="calendar__list-events", arguments={"calendarId": "primary"})
            self.requested_tool_names.append(call.name)
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        if last.role == "tool" and last.tool_call_id == "1":
            payload = json.loads(last.content)
            real_events = [
                event for event in payload["events"] if event.get("eventType") != "workingLocation"
            ]
            event = real_events[0]
            call = ToolCall(
                id="2",
                name="write_event",
                arguments={
                    "source": "calendar",
                    "type": "meeting",
                    "timestamp": "2026-07-06T09:00:00",
                    "metadata": {"summary": event["summary"], "attendees": event.get("attendees")},
                    "confidence": "proven",
                },
            )
            self.requested_tool_names.append(call.name)
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        if last.role == "tool" and last.tool_call_id == "2":
            call = ToolCall(
                id="3",
                name="flag_gap",
                arguments={"start_time": "2026-07-06T00:00:00", "end_time": "2026-07-06T23:59:59"},
            )
            self.requested_tool_names.append(call.name)
            return AgentResponse(text=None, tool_calls=[call], is_final=False)

        return AgentResponse(text="Recorded today's real meeting; no gap found.", tool_calls=[], is_final=True)


class TestFullAgentRunCalendarLocationExclusion:
    """
    Full-loop behavioral test: mocks the LLM (reactively, see
    `_ScriptedCalendarExclusionProvider`) and the Calendar MCP session, then
    drives the actual `run_agent` loop end to end -- not an isolated
    `Toolbelt.dispatch`/`write_event` call -- to prove the "Home" entry
    never reaches a real `write_event` DB write while the real "Team
    Standup" event does, and that flag_gap still runs as the final step.
    """

    def test_working_location_entry_never_reaches_write_event(self, monkeypatch):
        mock_session = AsyncMock()
        mock_session.call_tool.return_value = _mock_call_tool_result(
            {"events": [WORKING_LOCATION_EVENT, REAL_EVENT]}
        )

        async def fake_connect_mcp_source(self, source, build_params):
            if source == "calendar":
                self._sessions["calendar"] = mock_session
                self._mcp_tool_index["calendar__list-events"] = ("calendar", "list-events")
            # github/slack/jira intentionally left unconnected -- this test
            # only exercises the calendar location-exclusion path.

        monkeypatch.setattr(Toolbelt, "_connect_mcp_source", fake_connect_mcp_source)

        fake_write_db = MagicMock()
        fake_write_session_cm = MagicMock()
        fake_write_session_cm.__enter__.return_value = fake_write_db
        fake_write_session_cm.__exit__.return_value = False
        monkeypatch.setattr(write_event_module, "SessionLocal", lambda: fake_write_session_cm)

        fake_gap_query = MagicMock()
        fake_gap_query.filter.return_value.count.return_value = 1
        fake_gap_db = MagicMock()
        fake_gap_db.query.return_value = fake_gap_query
        fake_gap_session_cm = MagicMock()
        fake_gap_session_cm.__enter__.return_value = fake_gap_db
        fake_gap_session_cm.__exit__.return_value = False
        monkeypatch.setattr(flag_gap_module, "SessionLocal", lambda: fake_gap_session_cm)

        provider = _ScriptedCalendarExclusionProvider()
        monkeypatch.setattr(runner_module, "get_llm_provider", lambda: provider)

        result = asyncio.run(run_agent(user_id=1, task="Log today's calendar activity."))

        assert provider.requested_tool_names == ["calendar__list-events", "write_event", "flag_gap"]
        assert mock_session.call_tool.call_count == 1

        assert fake_write_db.add.call_count == 1
        written_event = fake_write_db.add.call_args.args[0]
        assert written_event.event_metadata["summary"] == "Team Standup"
        assert "Home" not in json.dumps(written_event.event_metadata)

        assert result.response_text == "Recorded today's real meeting; no gap found."
        assert result.created_entry_id is None
