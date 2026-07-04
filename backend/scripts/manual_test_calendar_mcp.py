"""Standalone script (not pytest) exercising a raw MCP protocol connection to
the community Google Calendar MCP server (@cocal/google-calendar-mcp),
spawned via `npx` over stdio. No Anthropic/OpenAI API call is made anywhere
in this script — it only tests that we can speak MCP to the Calendar server,
list its tools, and pull real calendar/event data back.

Requires GOOGLE_OAUTH_CREDENTIALS set in `backend/.env`, pointing at the
gcp-oauth.keys.json downloaded from the GCP OAuth client. Requires that the
one-time `npx @cocal/google-calendar-mcp auth` step has already been run so a
token is cached (the server reads that cache itself; this script never
touches OAuth directly). Requires Node.js/npx to be installed locally.

Run from `backend/` with the venv active:

    python scripts/manual_test_calendar_mcp.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

MAX_EVENTS_TO_SHOW = 5


def print_tool_result(result) -> None:
    for block in result.content:
        if hasattr(block, "text"):
            print(block.text)
        else:
            print(block)


async def main() -> None:
    credentials_path = os.environ.get("GOOGLE_OAUTH_CREDENTIALS")
    if not credentials_path:
        raise RuntimeError("GOOGLE_OAUTH_CREDENTIALS is not set in backend/.env")

    resolved_credentials_path = (BACKEND_DIR / credentials_path).resolve()
    if not resolved_credentials_path.is_file():
        raise RuntimeError(f"GOOGLE_OAUTH_CREDENTIALS points at a missing file: {resolved_credentials_path}")

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@cocal/google-calendar-mcp"],
        env={
            **os.environ,
            "GOOGLE_OAUTH_CREDENTIALS": str(resolved_credentials_path),
        },
    )

    print("[setup] spawning @cocal/google-calendar-mcp via npx...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[setup] MCP session initialized\n")

            print("--- Listing available tools ---")
            tools_result = await session.list_tools()
            print(f"Server exposes {len(tools_result.tools)} tools:\n")
            for tool in tools_result.tools:
                description = (tool.description or "").strip().splitlines()[0] if tool.description else ""
                print(f"  - {tool.name}: {description}")

            print("\n--- Calling list-calendars ---")
            calendars_result = await session.call_tool("list-calendars", arguments={})
            print_tool_result(calendars_result)

            print(f"\n--- Calling list-events (primary calendar, next {MAX_EVENTS_TO_SHOW} upcoming) ---")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            time_min = now.strftime("%Y-%m-%dT%H:%M:%S")
            time_max = (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
            events_result = await session.call_tool(
                "list-events",
                arguments={
                    "calendarId": "primary",
                    "timeMin": time_min,
                    "timeMax": time_max,
                },
            )
            # list-events has no server-side "limit" param; it returns all events in
            # the time window, already sorted chronologically, as a single JSON text
            # block — so we truncate client-side to honor the small-limit ask.
            payload = json.loads(events_result.content[0].text)
            payload["events"] = payload.get("events", [])[:MAX_EVENTS_TO_SHOW]
            print(json.dumps(payload, indent=2))

    print("\nAll checks passed: listed tools and got real results from the Calendar MCP server.")


if __name__ == "__main__":
    asyncio.run(main())
