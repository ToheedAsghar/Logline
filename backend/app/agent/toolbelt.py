"""Assembles the full toolbelt (MCP servers + custom tools) for an agent run.

MCP connection logic here is refactored out of `scripts/manual_test_*_mcp.py`
(same server commands/args/env per source, now reusable) rather than
duplicated. Custom tools (write_event, get_existing_events, flag_gap) are
registered using the same neutral `ToolDefinition` shape as MCP tools, so
`app/agent/runner.py` treats every tool uniformly regardless of source.

Credentials used here are the shared test tokens in `backend/.env` (see
backend/CLAUDE.md) — not yet per-user OAuth. `Toolbelt` takes a `user_id` only
to scope the custom tools' DB reads/writes; every user currently shares the
same MCP connections.
"""

import json
import logging
import os
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.agent.llm.base import ToolCall, ToolDefinition
from app.agent.tools.flag_gap import FlagGapInput, flag_gap
from app.agent.tools.get_existing_events import GetExistingEventsInput, get_existing_events
from app.agent.tools.write_draft_entry import DraftEntryInput, write_draft_entry
from app.agent.tools.write_event import WriteEventInput, write_event
from app.db.session import SessionLocal
from app.integrations.models import Integration, IntegrationSource

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

logger = logging.getLogger(__name__)

# Slack write tools are hard-restricted to this channel, mirroring the same
# guard in scripts/manual_test_slack_mcp.py — carried over unchanged so the
# agent inherits it too, not just the standalone test script.
SLACK_ALLOWED_CHANNEL_NAME = "logline_mcp_test"
SLACK_WRITE_TOOLS = {"slack_post_message", "slack_reply_to_thread", "slack_add_reaction"}

# These GitHub search tools require a repo:/org:/user: qualifier in the query
# to mean anything (see app/agent/system_prompt.py) — GitHub has no "search
# everywhere this user has been active" tool. If the user has an explicit repo
# list configured (Integration.integration_metadata["repos"]), we scope the
# query to it automatically rather than relying on the model to remember to.
GITHUB_SEARCH_TOOLS_REQUIRING_SCOPE = {"search_commits", "search_issues", "search_pull_requests"}
GITHUB_QUERY_SCOPE_QUALIFIERS = ("repo:", "org:", "user:")


def _github_server_params() -> StdioServerParameters:
    github_pat = os.environ.get("GITHUB_TEST_PAT")
    if not github_pat:
        raise RuntimeError("GITHUB_TEST_PAT is not set in backend/.env")
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


def _slack_server_params() -> StdioServerParameters:
    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_team_id = os.environ.get("SLACK_TEAM_ID")
    if not slack_bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set in backend/.env")
    if not slack_team_id:
        raise RuntimeError("SLACK_TEAM_ID is not set in backend/.env")
    return StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={"SLACK_BOT_TOKEN": slack_bot_token, "SLACK_TEAM_ID": slack_team_id},
    )


def _calendar_server_params() -> StdioServerParameters:
    credentials_path = os.environ.get("GOOGLE_OAUTH_CREDENTIALS")
    if not credentials_path:
        raise RuntimeError("GOOGLE_OAUTH_CREDENTIALS is not set in backend/.env")
    resolved_credentials_path = (BACKEND_DIR / credentials_path).resolve()
    if not resolved_credentials_path.is_file():
        raise RuntimeError(
            f"GOOGLE_OAUTH_CREDENTIALS points at a missing file: {resolved_credentials_path}"
        )
    return StdioServerParameters(
        command="npx",
        args=["-y", "@cocal/google-calendar-mcp"],
        env={**os.environ, "GOOGLE_OAUTH_CREDENTIALS": str(resolved_credentials_path)},
    )


def _jira_server_params() -> StdioServerParameters:
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


MCP_SERVER_BUILDERS: dict[str, Callable[[], StdioServerParameters]] = {
    "github": _github_server_params,
    "slack": _slack_server_params,
    "calendar": _calendar_server_params,
    "jira": _jira_server_params,
}

WRITE_DRAFT_ENTRY_TOOL_NAME = "write_draft_entry"

# Sources that must each have at least one MCP tool call attempted (success
# or failure both count -- this requires an attempt, not a finding) before
# write_draft_entry may succeed. flag_gap only answers "is there uncovered
# time in the events table", which is a different question from "did I check
# every connected source" -- a model can (and in live testing, did) conflate
# the two and write a draft having never touched github/slack/jira/calendar.
# A prompt-only fix isn't enough on its own (see DATE_GROUNDING's history of
# the same problem), so this is checked in code in Toolbelt.dispatch below.
#
# Scoped to whichever of these actually connected this run (self._sessions),
# not unconditionally all four: a source that failed to connect (e.g. a
# missing credential in a dev environment) registers no tool the model could
# possibly call, so requiring it would deadlock the agent forever.
DRAFT_ENTRY_REQUIRED_SOURCES = frozenset(MCP_SERVER_BUILDERS.keys())


def _schema_without_user_id(model: type) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.get("properties", {}).pop("user_id", None)
    if "required" in schema:
        schema["required"] = [f for f in schema["required"] if f != "user_id"]
    return schema


# (ToolDefinition, raw handler) — user_id is bound in at dispatch time so the
# model never has to know or guess it.
CUSTOM_TOOLS: list[tuple[ToolDefinition, Callable[..., Any]]] = [
    (
        ToolDefinition(
            name="get_existing_events",
            description=(
                "Look up events already recorded for this user in a time range. "
                "Call this first before fetching from MCP sources, to avoid redundant work."
            ),
            input_schema=_schema_without_user_id(GetExistingEventsInput),
        ),
        get_existing_events,
    ),
    (
        ToolDefinition(
            name="write_event",
            description=(
                "Persist a single work-log event. `confidence` must be 'proven' "
                "(directly evidenced by a tool result), 'estimated' (inferred, e.g. "
                "durations), or 'gap' (no data) — never invent a fourth value."
            ),
            input_schema=_schema_without_user_id(WriteEventInput),
        ),
        write_event,
    ),
    (
        ToolDefinition(
            name="flag_gap",
            description=(
                "Check whether a time range has no recorded events (a gap), computed "
                "dynamically from the events table. Does not write anything."
            ),
            input_schema=_schema_without_user_id(FlagGapInput),
        ),
        flag_gap,
    ),
    (
        ToolDefinition(
            name="write_draft_entry",
            description=(
                "Persist a synthesized standup or project log as a draft entry, once "
                "you've gathered and written the underlying evidence via write_event "
                "and checked flag_gap for uncovered time. `format` must be 'standup' "
                "(content: {yesterday, today, blockers}) or 'project_log' (content: "
                "{text}) — content is validated against that shape and the call is "
                "rejected if it doesn't match."
            ),
            input_schema=_schema_without_user_id(DraftEntryInput),
        ),
        write_draft_entry,
    ),
]


def _mcp_result_to_json(result: Any) -> Any:
    texts = [block.text for block in result.content if hasattr(block, "text")]
    combined = "\n".join(texts)
    try:
        return json.loads(combined)
    except (json.JSONDecodeError, ValueError):
        return combined


def get_user_github_repos(user_id: int) -> Optional[list[str]]:
    """Read the user's explicitly-configured GitHub repo list, if any.

    Reads `integrations.metadata["repos"]` (Python attribute
    `integration_metadata`) for this user's github integration — set once via
    a settings UI we haven't built yet. Returns None if there's no github
    integration row, no metadata, or no/empty `repos` key; callers should
    treat all of those as "nothing configured, fall back to live
    repo-discovery" rather than as an error.
    """
    with SessionLocal() as db:
        integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.source == IntegrationSource.github)
            .first()
        )
    if integration is None or not integration.integration_metadata:
        return None
    repos = integration.integration_metadata.get("repos")
    return repos or None


def _query_has_repo_scope(query: str) -> bool:
    return any(qualifier in query for qualifier in GITHUB_QUERY_SCOPE_QUALIFIERS)


# search_commits has no since:/until: qualifiers -- GitHub silently ignores
# them rather than erroring (see SYSTEM_PROMPT), which looks identical to "no
# commits in range" and is easy to miss. SYSTEM_PROMPT tells the model to use
# committer-date:YYYY-MM-DD..YYYY-MM-DD instead; this is the code-level
# backstop in case the model reverts to the invalid syntax anyway.
_GITHUB_INVALID_DATE_QUALIFIER_RE = re.compile(r"\b(since|until):(\S+)")


def _validate_github_date_syntax(query: str) -> str:
    matches = dict(_GITHUB_INVALID_DATE_QUALIFIER_RE.findall(query))
    if not matches:
        return query

    since_value = matches.get("since", "")
    until_value = matches.get("until", "")
    remainder = " ".join(_GITHUB_INVALID_DATE_QUALIFIER_RE.sub("", query).split())
    committer_date_qualifier = f"committer-date:{since_value}..{until_value}"
    return f"{remainder} {committer_date_qualifier}".strip()


# Code-level backstop for the date-grounding rule in SYSTEM_PROMPT (see step
# 0): the model is told to call calendar__get-current-time before reasoning
# about "today"/"this week"/etc., but a prompt is advisory, not enforced --
# live testing showed the model sometimes skips that call and hallucinates a
# literal date instead (e.g. a training-cutoff-ish date), which silently
# produces a wrong "no activity found" answer rather than an error. We can't
# know a literal date is *wrong* without an independent clock, so this can
# only flag "date used before grounding happened", not correctness -- logged
# as a warning rather than rejected, matching this file's existing
# auto-correct-don't-raise style for tool-call backstops.
DATE_GROUNDING_SOURCES = {"jira", "github", "calendar"}
CALENDAR_CURRENT_TIME_TOOL_NATIVE_NAME = "get-current-time"
# Lookarounds instead of \b: a plain \b fails to match the date prefix of an
# ISO datetime like "2024-01-19T00:00:00Z" -- "9" and "T" are both \w
# characters, so \b never breaks between them.
_LITERAL_DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def _contains_literal_date(arguments: dict[str, Any]) -> bool:
    return bool(_LITERAL_DATE_RE.search(json.dumps(arguments, default=str)))


SLACK_NOT_IN_CHANNEL_ERROR = "not_in_channel"

GET_SLACK_CHANNEL_ACTIVITY_TOOL = ToolDefinition(
    name="get_slack_channel_activity",
    description=(
        "Find a Slack channel by exact name (no leading '#') and read its message "
        "history, in one call. Paginates internally through the full channel list to "
        "resolve the name to an id, then calls slack_get_channel_history — you never "
        "need a separate lookup call first. If the name doesn't match any channel, or "
        "the bot isn't a member of it (native 'not_in_channel' result), this returns "
        "the channels the bot actually has access to as `member_channels` instead of "
        "just failing — pick a real name from that list and call this again rather "
        "than guessing another name blind. Calling this counts as having checked "
        "Slack regardless of outcome."
    ),
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Channel name, without '#'."}},
        "required": ["name"],
    },
)


async def _iter_all_slack_channels(session: ClientSession) -> AsyncIterator[dict[str, Any]]:
    cursor = None
    while True:
        args: dict[str, Any] = {"limit": 200}
        if cursor:
            args["cursor"] = cursor
        result = await session.call_tool("slack_list_channels", arguments=args)
        payload = _mcp_result_to_json(result)
        if not isinstance(payload, dict) or not payload.get("ok"):
            return
        for channel in payload.get("channels", []):
            yield channel
        cursor = (payload.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return


async def _find_slack_channel_id(session: ClientSession, name: str) -> Optional[str]:
    async for channel in _iter_all_slack_channels(session):
        if channel.get("name") == name:
            return channel["id"]
    return None


async def _list_member_slack_channels(session: ClientSession) -> list[dict[str, str]]:
    return [
        {"id": channel["id"], "name": channel["name"]}
        async for channel in _iter_all_slack_channels(session)
        if channel.get("is_member")
    ]


def _is_not_in_channel_result(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("ok") is False
        and payload.get("error") == SLACK_NOT_IN_CHANNEL_ERROR
    )


async def _get_slack_channel_activity(session: ClientSession, name: str) -> dict[str, Any]:
    """Resolve `name` to a channel id and read its history in one round trip.

    Falls back to the bot's actual member channels (rather than a bare
    not-found error) both when the name matches nothing and when it matches a
    channel the bot isn't a member of -- either way the agent needs the same
    next step: pick a real name and retry.
    """
    channel_id = await _find_slack_channel_id(session, name)
    if channel_id is not None:
        history_result = await session.call_tool(
            "slack_get_channel_history", arguments={"channel_id": channel_id}
        )
        history_payload = _mcp_result_to_json(history_result)
        if not _is_not_in_channel_result(history_payload):
            return {"found": True, "channel_id": channel_id, "history": history_payload}

    member_channels = await _list_member_slack_channels(session)
    return {
        "found": False,
        "requested_name": name,
        "member_channels": member_channels,
        "message": (
            f"No accessible channel named '{name}' found. Pick a real channel from "
            "member_channels and call get_slack_channel_activity again with its name."
        ),
    }


class Toolbelt:
    """The full set of tools available to one agent run, plus a dispatcher.

    Usage:
        async with Toolbelt(user_id=1) as toolbelt:
            response = await provider.run_turn(messages, toolbelt.tool_definitions)
            result = await toolbelt.dispatch(tool_call)
    """

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.tool_definitions: list[ToolDefinition] = []

        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._mcp_tool_index: dict[str, tuple[str, str]] = {}  # qualified name -> (source, native name)
        self._custom_handlers: dict[str, Callable[..., Any]] = {
            definition.name: handler for definition, handler in CUSTOM_TOOLS
        }
        self._slack_allowed_channel_id: Optional[str] = None
        self._current_time_established = False
        self._attempted_sources: set[str] = set()

    async def __aenter__(self) -> "Toolbelt":
        for source, build_params in MCP_SERVER_BUILDERS.items():
            await self._connect_mcp_source(source, build_params)

        if "slack" in self._sessions:
            self._slack_allowed_channel_id = await _find_slack_channel_id(
                self._sessions["slack"], SLACK_ALLOWED_CHANNEL_NAME
            )
            self.tool_definitions.append(GET_SLACK_CHANNEL_ACTIVITY_TOOL)

        self.tool_definitions.extend(definition for definition, _handler in CUSTOM_TOOLS)
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._exit_stack.aclose()

    async def _connect_mcp_source(
        self, source: str, build_params: Callable[[], StdioServerParameters]
    ) -> None:
        try:
            server_params = build_params()
            read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as exc:  # noqa: BLE001 - a down/misconfigured MCP server shouldn't kill the whole toolbelt
            print(f"[toolbelt] WARNING: could not connect '{source}' MCP server: {exc}")
            return

        self._sessions[source] = session
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            qualified_name = f"{source}__{tool.name}"
            self._mcp_tool_index[qualified_name] = (source, tool.name)
            self.tool_definitions.append(
                ToolDefinition(
                    name=qualified_name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                )
            )

    async def dispatch(self, tool_call: ToolCall) -> Any:
        if tool_call.name == "get_slack_channel_activity":
            # Marked unconditionally, in this single call site, regardless of
            # outcome -- this is what fixes the tracking bug where the old
            # three-step flow's find/list steps never reached the generic
            # MCP-tool-index branch below and so never counted as "attempted".
            self._attempted_sources.add("slack")
            if "slack" not in self._sessions:
                return {"error": "Slack MCP server is not connected."}
            return await _get_slack_channel_activity(
                self._sessions["slack"], tool_call.arguments["name"]
            )

        if tool_call.name in self._custom_handlers:
            if tool_call.name == WRITE_DRAFT_ENTRY_TOOL_NAME:
                missing = (DRAFT_ENTRY_REQUIRED_SOURCES & self._sessions.keys()) - self._attempted_sources
                if missing:
                    return {
                        "error": (
                            "Refused: write_draft_entry requires at least one tool call "
                            "attempted against every connected source first (finding "
                            "nothing is fine, skipping the attempt is not). Not yet "
                            f"attempted this run: {sorted(missing)}. Go check those "
                            "sources and then call write_draft_entry again."
                        )
                    }

            handler = self._custom_handlers[tool_call.name]
            try:
                return handler(user_id=self.user_id, **tool_call.arguments)
            except Exception as exc:  # noqa: BLE001 - surface tool errors back to the agent, don't crash the run
                return {"error": str(exc)}

        if tool_call.name in self._mcp_tool_index:
            source, native_name = self._mcp_tool_index[tool_call.name]
            self._attempted_sources.add(source)

            if source == "slack" and native_name in SLACK_WRITE_TOOLS:
                channel = tool_call.arguments.get("channel_id") or tool_call.arguments.get("channel")
                if not self._slack_allowed_channel_id or channel != self._slack_allowed_channel_id:
                    return {
                        "error": (
                            f"Refused: write tool '{native_name}' may only target "
                            f"#{SLACK_ALLOWED_CHANNEL_NAME} ({self._slack_allowed_channel_id})."
                        )
                    }

            arguments = dict(tool_call.arguments)

            if source == "calendar" and native_name == CALENDAR_CURRENT_TIME_TOOL_NATIVE_NAME:
                self._current_time_established = True
            elif not self._current_time_established and source in DATE_GROUNDING_SOURCES:
                if _contains_literal_date(arguments):
                    logger.warning(
                        "[date-grounding] %s called with a literal date before "
                        "calendar__get-current-time was ever called this run -- "
                        "the agent may be reasoning about 'today' using a "
                        "hallucinated or guessed date instead of the real "
                        "current time. arguments=%s",
                        tool_call.name,
                        arguments,
                    )

            if source == "github" and native_name in GITHUB_SEARCH_TOOLS_REQUIRING_SCOPE:
                query = _validate_github_date_syntax(arguments.get("query", ""))
                arguments["query"] = query
                if not _query_has_repo_scope(query):
                    stored_repos = get_user_github_repos(self.user_id)
                    if stored_repos:
                        scope = " ".join(f"repo:{repo}" for repo in stored_repos)
                        arguments["query"] = f"{scope} {query}".strip()

            if source == "calendar":
                # Only one Google account is ever connected in this shared-session
                # setup (see Toolbelt's module docstring) — dropping `account`
                # makes the calendar server use that sole account automatically
                # instead of the agent guessing a nickname like 'work'. Revisit
                # once per-user calendar OAuth with real multi-account support ships.
                arguments.pop("account", None)

            session = self._sessions[source]
            try:
                result = await session.call_tool(native_name, arguments=arguments)
            except Exception as exc:  # noqa: BLE001 - surface tool errors back to the agent, don't crash the run
                return {"error": str(exc)}
            return _mcp_result_to_json(result)

        return {"error": f"Unknown tool: {tool_call.name}"}
