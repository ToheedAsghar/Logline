"""Standalone script (not pytest) exercising a raw MCP protocol connection to
GitHub's official MCP server (ghcr.io/github/github-mcp-server), spawned via
Docker over stdio. No Anthropic/OpenAI API call is made anywhere in this
script — it only tests that we can speak MCP to the GitHub server, list its
tools, and get a real result back.

Requires GITHUB_TEST_PAT set in `backend/.env` (a fine-grained GitHub PAT,
read-only on contents/issues/PRs). Run from `backend/` with the venv active
and Docker running:

    python scripts/manual_test_github_mcp.py
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


async def main() -> None:
    github_pat = os.environ.get("GITHUB_TEST_PAT")
    if not github_pat:
        raise RuntimeError("GITHUB_TEST_PAT is not set in backend/.env")

    server_params = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITHUB_READ_ONLY=1",
            "ghcr.io/github/github-mcp-server",
        ],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": github_pat},
    )

    print("[setup] spawning ghcr.io/github/github-mcp-server via docker...")
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

            print("\n--- Calling get_me (read-only) ---")
            result = await session.call_tool("get_me", arguments={})
            print("Raw result:")
            for block in result.content:
                if hasattr(block, "text"):
                    print(block.text)
                else:
                    print(block)

    print("\nAll checks passed: listed tools and got a real result from GitHub's MCP server.")


if __name__ == "__main__":
    asyncio.run(main())
