"""Standalone script (not pytest) exercising the full agent runner loop --
real LLM, real app.agent.runner/toolbelt/tools code, unmodified -- but with
MOCKED MCP tool responses (no live GitHub/Slack/Jira/Calendar servers, no
live Postgres) so we can pin the model down to one deliberately ambiguous
scenario and see what confidence tier it actually reaches for.

Why this script exists: every real run against live MCP servers so far has
only ever produced clean "proven" or "gap" results, never "estimated". This
presents a case that is neither: a calendar event with a real title and real
attendees (something clearly happened -- not a gap) but no `end` field in
the mocked payload (the exact duration is not directly evidenced -- can't
honestly be "proven"). Per SYSTEM_PROMPT, that's exactly what "estimated"
exists for.

Requires OPENAI_API_KEY set in `backend/.env` -- a real OpenAI call is made,
only the MCP *data* is mocked, not the model. No Docker, no npx, no Postgres
required. Run from `backend/` with the venv active:

    python scripts/manual_test_confidence_tiering.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.llm.base import ToolDefinition
from app.agent.runner import run_agent
from app.agent.toolbelt import Toolbelt
import app.agent.tools.flag_gap as flag_gap_module
import app.agent.tools.get_existing_events as get_existing_events_module
import app.agent.tools.write_event as write_event_module

TEST_USER_ID = 1
TASK = (
    "Log what I worked on on 2026-07-06, using my calendar. Include how long "
    "each thing took."
)

# Real evidence something happened (title + attendees) but the exact
# duration is NOT directly evidenced -- there is no `end` key at all. This is
# the crux of the scenario: neither "proven" (duration isn't in the data)
# nor "gap" (something clearly did happen).
AMBIGUOUS_DURATION_EVENT = {
    "id": "evt-workshop-1",
    "summary": "Client Workshop: API Migration Planning",
    "attendees": [
        {"email": "toheed@arbisoft.com"},
        {"email": "client@example.com"},
        {"email": "pm@arbisoft.com"},
    ],
    "start": {"dateTime": "2026-07-06T14:00:00Z"},
    # deliberately no "end" field
}

CALENDAR_MOCK_TOOL_SCHEMAS = {
    "list-calendars": {
        "description": "List the calendars available to the user.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "list-events": {
        "description": "List events on a calendar within a date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendarId": {"type": "string"},
                "timeMin": {"type": "string"},
                "timeMax": {"type": "string"},
            },
            "required": ["calendarId"],
        },
    },
    "get-event": {
        "description": "Get a single event's full detail by id.",
        "input_schema": {
            "type": "object",
            "properties": {"calendarId": {"type": "string"}, "eventId": {"type": "string"}},
            "required": ["calendarId", "eventId"],
        },
    },
}


def _mock_call_tool_result(payload) -> MagicMock:
    result = MagicMock()
    result.content = [MagicMock(text=json.dumps(payload))]
    return result


async def _fake_connect_mcp_source(toolbelt_self, source, build_params) -> None:
    """Replaces Toolbelt._connect_mcp_source: wires up only a mocked calendar
    session so no live MCP server (and none of its credentials) is needed.
    github/slack/jira are intentionally left unconnected -- this test isolates
    the calendar duration-ambiguity case, mirroring how
    tests/test_calendar_location_exclusion.py isolates the location-exclusion
    case."""
    if source != "calendar":
        return

    async def fake_call_tool(name, arguments=None):
        if name == "list-calendars":
            return _mock_call_tool_result({"calendars": [{"id": "primary", "summary": "toheed@arbisoft.com"}]})
        if name == "list-events":
            return _mock_call_tool_result({"events": [AMBIGUOUS_DURATION_EVENT]})
        if name == "get-event":
            return _mock_call_tool_result(AMBIGUOUS_DURATION_EVENT)
        return _mock_call_tool_result({"error": f"unmocked calendar tool: {name}"})

    mock_session = AsyncMock()
    mock_session.call_tool.side_effect = fake_call_tool
    toolbelt_self._sessions["calendar"] = mock_session

    for native_name, schema in CALENDAR_MOCK_TOOL_SCHEMAS.items():
        qualified_name = f"calendar__{native_name}"
        toolbelt_self._mcp_tool_index[qualified_name] = ("calendar", native_name)
        toolbelt_self.tool_definitions.append(
            ToolDefinition(
                name=qualified_name,
                description=schema["description"],
                input_schema=schema["input_schema"],
            )
        )


def _db_session_stub(query_result_builder):
    """Builds a `with SessionLocal() as db:` stand-in whose db.query(...)
    chain returns whatever `query_result_builder` wires up, without needing a
    real Postgres connection."""
    fake_db = MagicMock()
    query_result_builder(fake_db)
    session_cm = MagicMock()
    session_cm.__enter__.return_value = fake_db
    session_cm.__exit__.return_value = False
    return fake_db, session_cm


def _confidence_tiering_analysis(write_calls: list, final_response: str) -> None:
    print("\n=== ANALYSIS ===")

    confidences = [event.confidence.value for event in write_calls]
    print(f"Confidence tiers written: {confidences or '(none)'}")

    has_estimated = "estimated" in confidences
    has_gap = "gap" in confidences
    only_proven = bool(confidences) and all(c == "proven" for c in confidences)
    wrote_nothing = not write_calls

    if has_estimated:
        print("PASS: agent produced an 'estimated' confidence tier for the ambiguous event.")
    elif only_proven:
        print(
            "FLAG (not cautious enough OR silently under-inferring): every write_event call "
            "was tagged 'proven'. Either the agent fabricated a duration and marked it proven "
            "(bad), or it wrote the event as proven while quietly omitting the ambiguous "
            "duration fact entirely (better than fabricating, but still never exercises the "
            "'estimated' tier the system prompt calls for)."
        )
    elif has_gap and wrote_nothing:
        print(
            "FLAG (over-cautious): agent treated the event as a pure gap despite real evidence "
            "(a titled meeting with named attendees) that something happened. It should have "
            "recorded the meeting as proven/estimated and only flagged the *unknown duration* "
            "part as uncertain, not thrown out the whole thing."
        )
    elif wrote_nothing:
        print("FLAG: agent wrote no events at all for a scenario with clear (if partial) evidence.")

    editable_markers = ["estimat", "edit", "correct", "adjust", "approx", "unsure", "confirm", "not sure exactly"]
    mentions_editability = any(marker in final_response.lower() for marker in editable_markers)
    print(
        f"Final response {'DOES' if mentions_editability else 'does NOT'} surface the duration "
        "as something the user should be able to edit/correct."
    )


async def main() -> None:
    trace: list[dict] = []
    original_dispatch = Toolbelt.dispatch

    async def traced_dispatch(self, tool_call):
        result = await original_dispatch(self, tool_call)
        trace.append({"tool": tool_call.name, "arguments": tool_call.arguments, "result": result})
        return result

    write_calls: list = []
    fake_write_db, fake_write_session_cm = _db_session_stub(
        lambda db: setattr(db.add, "side_effect", write_calls.append)
    )

    def _existing_events_query(db):
        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query
        query.all.return_value = []
        db.query.return_value = query

    fake_existing_db, fake_existing_session_cm = _db_session_stub(_existing_events_query)

    def _gap_query(db):
        query = MagicMock()
        query.filter.return_value.count.return_value = 1
        db.query.return_value = query

    fake_gap_db, fake_gap_session_cm = _db_session_stub(_gap_query)

    with patch.object(Toolbelt, "_connect_mcp_source", _fake_connect_mcp_source), \
         patch.object(Toolbelt, "dispatch", traced_dispatch), \
         patch.object(write_event_module, "SessionLocal", lambda: fake_write_session_cm), \
         patch.object(get_existing_events_module, "SessionLocal", lambda: fake_existing_session_cm), \
         patch.object(flag_gap_module, "SessionLocal", lambda: fake_gap_session_cm):

        print(f"[task] user_id={TEST_USER_ID} task={TASK!r}\n")
        result = await run_agent(user_id=TEST_USER_ID, task=TASK)
        final_response = result.response_text

    print("=== FULL TOOL-CALL TRACE ===")
    for i, step in enumerate(trace, start=1):
        print(f"\n[{i}] {step['tool']}({json.dumps(step['arguments'])})")
        print(f"    -> {json.dumps(step['result'], default=str)}")

    print("\n=== write_event CALLS (captured, no real DB) ===")
    for event in write_calls:
        print(
            f"  source={event.source!r} type={event.type!r} timestamp={event.timestamp} "
            f"confidence={event.confidence.value!r} metadata={event.event_metadata}"
        )

    print("\n=== FINAL AGENT RESPONSE ===")
    print(final_response)

    _confidence_tiering_analysis(write_calls, final_response or "")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
