"""Standalone script (not pytest) exercising a raw MCP protocol connection to
Slack's official MCP server (@modelcontextprotocol/server-slack), spawned via
`npx` over stdio. No Anthropic/OpenAI API call is made anywhere in this
script — it only tests that we can speak MCP to the Slack server, list its
tools, and pull real channel history.

Requires SLACK_BOT_TOKEN and SLACK_TEAM_ID set in `backend/.env`. Requires
Node.js/npx to be installed locally. Run from `backend/` with the venv active:

    python scripts/manual_test_slack_mcp.py

IMPORTANT — this token is connected to the real Arbisoft Slack workspace, not
a demo one. All testing here is restricted to the #logline_mcp_test channel.
`call_tool_restricted` refuses to invoke any write tool (post/reply/react)
against any channel other than ALLOWED_CHANNEL_NAME, no matter what a caller
passes in — this is a hard guard, not just a convention, so it still holds if
this script grows write-path tests later.
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ALLOWED_CHANNEL_NAME = "logline_mcp_test"
WRITE_TOOLS = {"slack_post_message", "slack_reply_to_thread", "slack_add_reaction"}


def print_tool_result(result) -> None:
    for block in result.content:
        if hasattr(block, "text"):
            print(block.text)
        else:
            print(block)


async def call_tool_restricted(session: ClientSession, tool_name: str, arguments: dict, allowed_channel_id: str):
    if tool_name in WRITE_TOOLS:
        channel_id = arguments.get("channel_id") or arguments.get("channel")
        if channel_id != allowed_channel_id:
            raise RuntimeError(
                f"Refusing to call write tool {tool_name!r} against channel "
                f"{channel_id!r} — only #{ALLOWED_CHANNEL_NAME} ({allowed_channel_id}) "
                "is permitted for write actions."
            )
    return await session.call_tool(tool_name, arguments=arguments)


async def find_channel_by_name(session: ClientSession, name: str) -> dict | None:
    cursor = None
    while True:
        args = {"limit": 200}
        if cursor:
            args["cursor"] = cursor
        result = await session.call_tool("slack_list_channels", arguments=args)
        for block in result.content:
            text = getattr(block, "text", None)
            if not text:
                continue
            payload = json.loads(text)
            if not payload.get("ok"):
                raise RuntimeError(f"slack_list_channels failed: {payload}")
            for channel in payload.get("channels", []):
                if channel.get("name") == name:
                    return channel
            cursor = (payload.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return None


async def main() -> None:
    if shutil.which("npx") is None:
        raise RuntimeError(
            "npx was not found on PATH. Install Node.js (which bundles npx) "
            "before running this script."
        )

    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_team_id = os.environ.get("SLACK_TEAM_ID")
    if not slack_bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set in backend/.env")
    if not slack_team_id:
        raise RuntimeError("SLACK_TEAM_ID is not set in backend/.env")

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={
            "SLACK_BOT_TOKEN": slack_bot_token,
            "SLACK_TEAM_ID": slack_team_id,
        },
    )

    print("[setup] spawning @modelcontextprotocol/server-slack via npx...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[setup] MCP session initialized\n")

            print("--- Listing available tools ---")
            tools_result = await session.list_tools()
            print(f"Server exposes {len(tools_result.tools)} tools:\n")
            for tool in tools_result.tools:
                description = (
                    (tool.description or "").strip().splitlines()[0]
                    if tool.description
                    else ""
                )
                print(f"  - {tool.name}: {description}")

            print(f"\n--- Looking up #{ALLOWED_CHANNEL_NAME} via slack_list_channels (read-only) ---")
            channel = await find_channel_by_name(session, ALLOWED_CHANNEL_NAME)

            if channel is None:
                print(
                    f"\n#{ALLOWED_CHANNEL_NAME} was not found via slack_list_channels. "
                    "This can happen if the channel is private/not visible to the bot "
                    "with its current scopes, even after being invited. Not fetching "
                    "history for any other channel per testing restrictions."
                )
                return

            channel_id = channel["id"]
            print(f"Found #{ALLOWED_CHANNEL_NAME} -> {channel_id}")

            print(f"\n--- Calling slack_get_channel_history for #{ALLOWED_CHANNEL_NAME} ({channel_id}) ---")
            history_result = await call_tool_restricted(
                session,
                "slack_get_channel_history",
                {"channel_id": channel_id},
                allowed_channel_id=channel_id,
            )
            print("Raw result:")
            print_tool_result(history_result)
            print(
                "\nNote: if the message list above is empty, this is expected if "
                "there are simply no messages posted yet in the channel — not "
                "necessarily a failure of the MCP connection."
            )

    print("\nAll checks passed: listed tools and got a real result from Slack's MCP server.")


if __name__ == "__main__":
    asyncio.run(main())
