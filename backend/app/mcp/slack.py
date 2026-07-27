"""Provides Slack channel listing and channel ID resolution functions using MCP."""

from typing import Any, AsyncIterator, Optional

from mcp import ClientSession

from app.mcp.connection import mcp_result_to_json

SLACK_CHANNELS_PAGE_LIMIT = 200


async def iter_all_slack_channels(session: ClientSession) -> AsyncIterator[dict[str, Any]]:
    cursor = None
    while True:
        args: dict[str, Any] = {"limit": SLACK_CHANNELS_PAGE_LIMIT}
        if cursor:
            args["cursor"] = cursor
        result = await session.call_tool("slack_list_channels", arguments=args)
        payload = mcp_result_to_json(result)
        if not isinstance(payload, dict) or not payload.get("ok"):
            return
        for channel in payload.get("channels", []):
            yield channel
        cursor = (payload.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return


async def find_slack_channel_id(session: ClientSession, name: str) -> Optional[str]:
    async for channel in iter_all_slack_channels(session):
        if channel.get("name") == name:
            return channel["id"]
    return None


async def list_member_slack_channels(session: ClientSession) -> list[dict[str, str]]:
    """Return channels where the authenticated bot is a member."""

    return [
        {"id": channel["id"], "name": channel["name"]}
        async for channel in iter_all_slack_channels(session)
        if channel.get("is_member")
    ]
