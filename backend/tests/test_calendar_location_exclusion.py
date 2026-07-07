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
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.llm.base import ToolCall
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.toolbelt import Toolbelt
from app.agent.tools.flag_gap import flag_gap
from app.agent.tools.write_event import write_event
import app.agent.tools.flag_gap as flag_gap_module
import app.agent.tools.write_event as write_event_module

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
    import json

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
