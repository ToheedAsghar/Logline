"""Provides functions to initialize raw MCP ClientSession connections for remote sources."""

import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.remote_fetch.constants import (
    ENV_GITHUB_TEST_PAT, ENV_GOOGLE_OAUTH_CREDENTIALS, ENV_JIRA_API_TOKEN, ENV_JIRA_EMAIL, ENV_JIRA_SITE_URL,
    ENV_SLACK_BOT_TOKEN, ENV_SLACK_TEAM_ID,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent

logger = logging.getLogger(__name__)

MCP_SERVER_BUILDERS: dict[str, Callable[[], StdioServerParameters]] = {}


def register_mcp_builder(
    source: str,
) -> Callable[[Callable[[], StdioServerParameters]], Callable[[], StdioServerParameters]]:
    """Register an MCP server parameter builder function for a remote source."""

    def decorator(fn: Callable[[], StdioServerParameters]) -> Callable[[], StdioServerParameters]:
        MCP_SERVER_BUILDERS[source] = fn
        return fn

    return decorator


@register_mcp_builder("github")
def github_server_params() -> StdioServerParameters:
    github_pat = os.environ.get(ENV_GITHUB_TEST_PAT)
    if not github_pat:
        raise RuntimeError(f"{ENV_GITHUB_TEST_PAT} is not set in backend/.env")
    return StdioServerParameters(
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


@register_mcp_builder("slack")
def slack_server_params() -> StdioServerParameters:
    slack_bot_token = os.environ.get(ENV_SLACK_BOT_TOKEN)
    slack_team_id = os.environ.get(ENV_SLACK_TEAM_ID)
    if not slack_bot_token:
        raise RuntimeError(f"{ENV_SLACK_BOT_TOKEN} is not set in backend/.env")
    if not slack_team_id:
        raise RuntimeError(f"{ENV_SLACK_TEAM_ID} is not set in backend/.env")
    return StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={ENV_SLACK_BOT_TOKEN: slack_bot_token, ENV_SLACK_TEAM_ID: slack_team_id},
    )


@register_mcp_builder("calendar")
def calendar_server_params() -> StdioServerParameters:
    credentials_path = os.environ.get(ENV_GOOGLE_OAUTH_CREDENTIALS)

    if not credentials_path:
        raise RuntimeError(f"{ENV_GOOGLE_OAUTH_CREDENTIALS} is not set in backend/.env")
    resolved_credentials_path = (BACKEND_DIR / credentials_path).resolve()
    if not resolved_credentials_path.is_file():
        raise RuntimeError(
            f"{ENV_GOOGLE_OAUTH_CREDENTIALS} points at a missing file: {resolved_credentials_path}"
        )
    return StdioServerParameters(
        command="npx",
        args=["-y", "@cocal/google-calendar-mcp"],
        env={**os.environ, ENV_GOOGLE_OAUTH_CREDENTIALS: str(resolved_credentials_path)},
    )


@register_mcp_builder("jira")
def jira_server_params() -> StdioServerParameters:
    jira_api_token = os.environ.get(ENV_JIRA_API_TOKEN)
    jira_email = os.environ.get(ENV_JIRA_EMAIL)
    jira_site_url = os.environ.get(ENV_JIRA_SITE_URL)
    if not jira_api_token:
        raise RuntimeError(f"{ENV_JIRA_API_TOKEN} is not set in backend/.env")
    if not jira_email:
        raise RuntimeError(f"{ENV_JIRA_EMAIL} is not set in backend/.env")
    if not jira_site_url:
        raise RuntimeError(f"{ENV_JIRA_SITE_URL} is not set in backend/.env")
    if not jira_site_url.startswith("http://") and not jira_site_url.startswith("https://"):
        jira_site_url = f"https://{jira_site_url}"
    return StdioServerParameters(
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
        env={"JIRA_URL": jira_site_url, "JIRA_USERNAME": jira_email, "JIRA_API_TOKEN": jira_api_token},
    )


def mcp_result_to_json(result: Any) -> Any:
    """Flatten an MCP tool result's text blocks and parse them as JSON.

    Falls back to the raw joined text when it isn't valid JSON -- several
    servers return prose on error, and losing that message would leave the
    caller with nothing to log.
    """

    texts = [block.text for block in result.content if hasattr(block, "text")]
    combined = "\n".join(texts)
    try:
        return json.loads(combined)
    except (json.JSONDecodeError, ValueError):
        return combined


async def connect_mcp_source(
    source: str,
    exit_stack: AsyncExitStack,
    build_params: Optional[Callable[[], StdioServerParameters]] = None,
) -> Optional[ClientSession]:
    """Spawn `source`'s MCP server and return an initialized session, or None.

    A down or misconfigured server returns None rather than raising: every
    caller here is fetching from four independent sources, and one missing
    credential must never take the other three down with it. The session's
    lifetime is owned by `exit_stack`, so closing that stack shuts the
    server down.
    """

    if build_params is None:
        build_params = MCP_SERVER_BUILDERS[source]

    try:
        server_params = build_params()
        read, write = await exit_stack.enter_async_context(stdio_client(server_params))
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
    except (RuntimeError, OSError, Exception) as exc:
        logger.warning("could not connect '%s' MCP server: %s", source, exc)
        return None

    return session
