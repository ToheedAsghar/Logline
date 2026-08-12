"""Provides Slack channel listing, ID resolution, and message fetch functions using MCP.

Filters messages to include only those authored by the connected user and
skips fetching when user identity resolution is unavailable.
"""

import logging
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from mcp import ClientSession

from app.integrations.config import get_mapped_remote_project_ids
from app.remote_fetch.base import FetchedEvent, SourceFetchData, SourceFetcher
from app.remote_fetch.constants import (
    IGNORED_SLACK_MESSAGE_SUBTYPES, MAX_EVENTS_PER_SOURCE, SLACK_CHANNELS_PAGE_LIMIT, SLACK_HISTORY_PAGE_LIMIT,
)
from app.remote_fetch.mcp.connection import mcp_result_to_json
from app.remote_fetch.parsing import first_non_empty_string, parse_slack_ts

logger = logging.getLogger(__name__)

SOURCE = "slack"
EVENT_TYPE_MESSAGE = "message"


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


def resolve_connected_slack_user_id() -> Optional[str]:
    """Return the connected user's Slack identity, or None if unavailable.

    Per-user Slack ID resolution requires OAuth user tokens. Returns None until
    per-user resolution is supported.
    """
    return None


def _message_event(
    message: dict[str, Any], channel_id: str, channel_name: Optional[str], connected_user_id: str
) -> Optional[FetchedEvent]:
    """Build a FetchedEvent from a Slack message payload.

    Returns None for system/bot subtypes or messages from other authors.
    """

    if message.get("subtype") in IGNORED_SLACK_MESSAGE_SUBTYPES:
        return None

    ts = first_non_empty_string(message.get("ts"))
    if ts is None:
        return None

    occurred_at = parse_slack_ts(ts)
    if occurred_at is None:
        return None

    user = first_non_empty_string(message.get("user"), message.get("bot_id"))
    if user != connected_user_id:
        return None

    text = first_non_empty_string(message.get("text"))
    channel_label = f"#{channel_name}" if channel_name else channel_id
    thread_ts = first_non_empty_string(message.get("thread_ts"))

    summary = f"Message in {channel_label}"
    if user:
        summary = f"{summary} by {user}"
    if thread_ts and thread_ts != ts:
        summary = f"{summary} (thread reply)"

    return FetchedEvent(
        source=SOURCE,
        event_type=EVENT_TYPE_MESSAGE,
        external_id=f"{channel_id}:{ts}",
        occurred_at=occurred_at,
        summary=summary,
        description=text,
        remote_project_id=channel_id,
        match_keys={
            "channel_id": channel_id,
            "channel_name": channel_name,
            "user": user,
            "thread_ts": thread_ts,
        },
        raw_data=message,
    )


class SlackFetcher(SourceFetcher):
    source = SOURCE

    async def fetch_with_session(
        self, session: ClientSession, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        """Fetches this user's Slack messages since the given time.

        Skips fetching entirely if no connected Slack identity is found, rather than recording every
        message in a shared channel as this user's own.
        """
        connected_user_id = resolve_connected_slack_user_id()
        if connected_user_id is None:
            logger.warning("slack_connected_user_identity_unavailable", extra={"user_id": user_id})
            return SourceFetchData(events=[])

        channels = await self._resolve_channels(session, user_id)
        if not channels:
            logger.info("slack_no_readable_channels", extra={"user_id": user_id})
            return SourceFetchData(events=[])

        events: list[FetchedEvent] = []
        oldest_seen: Optional[datetime] = None

        for channel_id, channel_name in channels:
            channel_events, channel_oldest = await self._fetch_channel(
                session, channel_id, channel_name, since, connected_user_id
            )
            events.extend(channel_events)
            if channel_oldest is not None and (oldest_seen is None or channel_oldest < oldest_seen):
                oldest_seen = channel_oldest

        events.sort(key=lambda event: event.occurred_at)
        return SourceFetchData(
            events=events[:MAX_EVENTS_PER_SOURCE], fetched_through_override=oldest_seen
        )

    async def _resolve_channels(
        self, session: ClientSession, user_id: int
    ) -> list[tuple[str, Optional[str]]]:
        mapped = (
            self.remote_fetch_config.projects_for(SOURCE)
            if self.remote_fetch_config is not None
            else get_mapped_remote_project_ids(user_id, SOURCE)
        )
        if mapped:
            return [(channel_id, None) for channel_id in mapped]

        logger.info("slack_no_project_mappings_falling_back_to_member_channels", extra={"user_id": user_id})
        return [(channel["id"], channel.get("name")) for channel in await list_member_slack_channels(session)]

    async def _fetch_channel(
        self,
        session: ClientSession,
        channel_id: str,
        channel_name: Optional[str],
        since: Optional[datetime],
        connected_user_id: str,
    ) -> tuple[list[FetchedEvent], Optional[datetime]]:
        """Fetch and filter recent messages for a single Slack channel.

        Returns matching events and an optional high-water mark override if the page was truncated. Slack's
        history call has no cursor for paging further back, so on truncation the high-water mark is held at
        the oldest message seen instead of advancing, so the next run re-covers this range.
        """

        result = await session.call_tool(
            "slack_get_channel_history",
            arguments={"channel_id": channel_id, "limit": SLACK_HISTORY_PAGE_LIMIT},
        )
        payload = mcp_result_to_json(result)

        if isinstance(payload, dict) and payload.get("ok") is False:
            logger.warning(
                "slack_channel_history_read_failed",
                extra={"channel_id": channel_id, "error": payload.get("error")},
            )
            return [], None

        messages = _messages_from_payload(payload)
        events: list[FetchedEvent] = []
        oldest_in_page: Optional[datetime] = None

        for message in messages:
            if message.get("subtype") in IGNORED_SLACK_MESSAGE_SUBTYPES:
                continue
            ts = first_non_empty_string(message.get("ts"))
            message_occurred_at = parse_slack_ts(ts) if ts is not None else None
            if message_occurred_at is None:
                continue
            if oldest_in_page is None or message_occurred_at < oldest_in_page:
                oldest_in_page = message_occurred_at

            event = _message_event(message, channel_id, channel_name, connected_user_id)
            if event is None:
                continue
            if since is not None and event.occurred_at <= since:
                continue
            events.append(event)

        truncated = len(messages) >= SLACK_HISTORY_PAGE_LIMIT
        if truncated and oldest_in_page is not None:
            logger.warning(
                "slack_channel_history_page_truncated",
                extra={
                    "channel_id": channel_id,
                    "message_count": len(messages),
                    "oldest_seen": oldest_in_page.isoformat(),
                },
            )
            return events, oldest_in_page

        return events, None


def _messages_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get("messages")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []
