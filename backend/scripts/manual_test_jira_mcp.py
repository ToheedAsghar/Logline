"""Standalone script (not pytest) exercising a raw MCP protocol connection to
the community Jira/Confluence MCP server (ghcr.io/sooperset/mcp-atlassian),
spawned via Docker over stdio. No Anthropic/OpenAI API call is made anywhere
in this script — it only tests that we can speak MCP to the Jira server, list
its tools, and get a real result back from a read-only search.

Requires JIRA_API_TOKEN, JIRA_EMAIL, and JIRA_SITE_URL set in `backend/.env`.
Run from `backend/` with the venv active and Docker running:

    python scripts/manual_test_jira_mcp.py
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def print_tool_result(result) -> None:
    for block in result.content:
        if hasattr(block, "text"):
            print(block.text)
        else:
            print(block)


async def main() -> None:
    jira_api_token = os.environ.get("JIRA_API_TOKEN")
    jira_email = os.environ.get("JIRA_EMAIL")
    jira_site_url = os.environ.get("JIRA_SITE_URL")

    if not jira_api_token:
        raise RuntimeError("JIRA_API_TOKEN is not set in backend/.env")
    if not jira_email:
        raise RuntimeError("JIRA_EMAIL is not set in backend/.env")
    if not jira_site_url:
        raise RuntimeError("JIRA_SITE_URL is not set in backend/.env")

    if not jira_site_url.startswith("http://") and not jira_site_url.startswith("https://"):
        jira_site_url = f"https://{jira_site_url}"

    server_params = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "JIRA_URL",
            "-e",
            "JIRA_USERNAME",
            "-e",
            "JIRA_API_TOKEN",
            "ghcr.io/sooperset/mcp-atlassian",
        ],
        env={
            "JIRA_URL": jira_site_url,
            "JIRA_USERNAME": jira_email,
            "JIRA_API_TOKEN": jira_api_token,
        },
    )

    print("[setup] spawning ghcr.io/sooperset/mcp-atlassian via docker...")
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

            search_tool = next(
                (t for t in tools_result.tools if t.name == "jira_search"),
                None,
            ) or next(
                (t for t in tools_result.tools if "search" in t.name and "jira" in t.name),
                None,
            )
            if search_tool is None:
                raise RuntimeError(
                    "No jira search tool found among the server's exposed tools; "
                    "cannot run the read-only search check."
                )

            jql = "assignee = currentUser() order by created DESC"
            print(f"\n--- Calling {search_tool.name} (read-only, limit 5, jql={jql!r}) ---")
            result = await session.call_tool(
                search_tool.name,
                arguments={"jql": jql, "limit": 5},
            )
            print("Raw result:")
            print_tool_result(result)

    print("\nAll checks passed: listed tools and got a real result from Jira's MCP server.")


if __name__ == "__main__":
    asyncio.run(main())
