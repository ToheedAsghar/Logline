"""Fetches Slack messages via the Slack Web API and normalizes them into events.

Filters messages to include only those authored by the connected user -- identified by
`OAuthToken.authed_user_id`, resolved generically by `SourceFetcher.fetch` -- and skips fetching
entirely when that identity is unavailable.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import httpx

from app.integrations.config import get_mapped_remote_project_ids
from app.remote_fetch.base import FetchedEvent, SourceCredentials, SourceFetchData, SourceFetcher, SourceUnavailable
from app.remote_fetch.constants import MAX_EVENTS_PER_SOURCE
from app.remote_fetch.parsing import first_non_empty_string, parse_slack_ts

logger = logging.getLogger(__name__)

SOURCE = "slack"
EVENT_TYPE_MESSAGE = "message"

SLACK_API_BASE_URL = "https://slack.com/api"
# Includes `im` (DMs) alongside channels -- a deliberate, already-approved scope expansion over
# the old MCP tool, which only ever listed channels.
SLACK_CONVERSATION_TYPES = "public_channel,private_channel,im"

SLACK_HISTORY_PAGE_LIMIT = 200
SLACK_CHANNELS_PAGE_LIMIT = 200
# Real per-channel cap on `conversations.history` cursor pages, since the Slack Web API paginates
# genuinely (unlike the old MCP tool) -- a channel this deep in one fetch window would be
# pathological, so this is a safety valve, not an expected truncation point.
SLACK_HISTORY_MAX_PAGES = 10

SLACK_RATE_LIMIT_MAX_RETRIES = 3
SLACK_RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS = 5.0


async def _get_with_rate_limit_retry(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], params: dict[str, Any]
) -> httpx.Response:
    """GET with a bounded retry on Slack's 429, honoring its `Retry-After` header.

    Live testing against a real, large workspace showed this is a real (not hypothetical) risk --
    Slack's Tier 2/3 per-method rate limits are tight enough that paginating a busy account trips
    them. Retrying a few times with the server-specified backoff is enough for that case; a source
    still rate-limited after this many attempts raises SourceUnavailable so the orchestrator records
    a visible failure rather than this call crashing the whole fetch.
    """

    for attempt in range(SLACK_RATE_LIMIT_MAX_RETRIES + 1):
        response = await client.get(url, headers=headers, params=params)
        if response.status_code != 429:
            return response
        if attempt == SLACK_RATE_LIMIT_MAX_RETRIES:
            raise SourceUnavailable(f"slack rate limited after {attempt + 1} attempts calling {url}")
        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after is not None else SLACK_RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS
        except ValueError:
            delay = SLACK_RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS
        logger.warning("slack_rate_limited_retrying", extra={"url": url, "attempt": attempt, "delay": delay})
        await asyncio.sleep(delay)


IGNORED_SLACK_MESSAGE_SUBTYPES = frozenset(
    {
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "channel_unarchive",
        "bot_message",
    }
)


def _auth_headers(credentials: SourceCredentials) -> dict[str, str]:
    return {"Authorization": f"Bearer {credentials.access_token}"}


def _conversation_display_name(channel: dict[str, Any]) -> Optional[str]:
    if channel.get("is_im"):
        counterpart = first_non_empty_string(channel.get("user"))
        return f"DM with {counterpart}" if counterpart else None
    return first_non_empty_string(channel.get("name"))


def _slack_ts_param(value: datetime) -> str:
    return f"{value.timestamp():.6f}"


async def iter_all_slack_conversations(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> AsyncIterator[dict[str, Any]]:
    """Yield every conversation the connected user is a member of.

    Uses `users.conversations`, not `conversations.list` -- the latter enumerates every
    conversation of the requested types *in the whole workspace* (public/private channels the
    token can merely see, not just ones this user is in), which for a large workspace means paging
    through thousands of irrelevant channels to find the handful this user actually belongs to.
    Live testing against a real ~1000-channel workspace hit Slack's rate limit doing exactly that.
    `users.conversations` takes the same `types` filter but is pre-scoped to membership, so every
    yielded item is already readable -- no separate `is_member` check needed.
    """

    cursor = None
    while True:
        params: dict[str, Any] = {"types": SLACK_CONVERSATION_TYPES, "limit": SLACK_CHANNELS_PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        url = f"{SLACK_API_BASE_URL}/users.conversations"
        response = await _get_with_rate_limit_retry(client, url, headers, params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("ok"):
            logger.warning(
                "slack_users_conversations_failed",
                extra={"error": payload.get("error") if isinstance(payload, dict) else None},
            )
            return
        for channel in payload.get("channels", []):
            yield channel
        cursor = (payload.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return


async def find_slack_conversation_id(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> Optional[str]:
    async for channel in iter_all_slack_conversations(client, headers):
        if channel.get("name") == name:
            return channel["id"]
    return None


async def list_member_slack_conversations(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> list[dict[str, Optional[str]]]:
    """Return conversations (channels and DMs) the connected user is actually part of."""

    return [
        {"id": channel["id"], "name": _conversation_display_name(channel)}
        async for channel in iter_all_slack_conversations(client, headers)
    ]


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

    async def fetch_with_client(
        self, client: httpx.AsyncClient, credentials: SourceCredentials, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        """Fetches this user's Slack messages since the given time.

        Skips fetching entirely if no connected Slack identity is known, rather than recording every
        message in a shared channel as this user's own.
        """

        connected_user_id = credentials.authed_user_id
        if not connected_user_id:
            logger.warning("slack_connected_user_identity_unavailable", extra={"user_id": user_id})
            return SourceFetchData(events=[])

        headers = _auth_headers(credentials)
        conversations = await self._resolve_conversations(client, headers, user_id)
        if not conversations:
            logger.info("slack_no_readable_conversations", extra={"user_id": user_id})
            return SourceFetchData(events=[])

        events: list[FetchedEvent] = []
        oldest_seen: Optional[datetime] = None

        for channel_id, channel_name in conversations:
            channel_events, channel_oldest = await self._fetch_channel(
                client, headers, channel_id, channel_name, since, connected_user_id
            )
            events.extend(channel_events)
            if channel_oldest is not None and (oldest_seen is None or channel_oldest < oldest_seen):
                oldest_seen = channel_oldest

        events.sort(key=lambda event: event.occurred_at)
        return SourceFetchData(
            events=events[:MAX_EVENTS_PER_SOURCE], fetched_through_override=oldest_seen
        )

    async def _resolve_conversations(
        self, client: httpx.AsyncClient, headers: dict[str, str], user_id: int
    ) -> list[tuple[str, Optional[str]]]:
        mapped = (
            self.remote_fetch_config.projects_for(SOURCE)
            if self.remote_fetch_config is not None
            else get_mapped_remote_project_ids(user_id, SOURCE)
        )
        if mapped:
            return [(channel_id, None) for channel_id in mapped]

        logger.info("slack_no_project_mappings_falling_back_to_member_conversations", extra={"user_id": user_id})
        conversations = await list_member_slack_conversations(client, headers)
        return [(conversation["id"], conversation["name"]) for conversation in conversations]

    async def _fetch_channel(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        channel_id: str,
        channel_name: Optional[str],
        since: Optional[datetime],
        connected_user_id: str,
    ) -> tuple[list[FetchedEvent], Optional[datetime]]:
        """Fetch and filter this channel's messages since `since`, following real cursor pagination.

        Returns matching events and an optional high-water mark override, held back only if
        SLACK_HISTORY_MAX_PAGES is exhausted without the cursor running out -- an expected-to-be-rare
        case now that both server-side `oldest` filtering and real cursor pagination are available.
        """

        events: list[FetchedEvent] = []
        oldest_seen: Optional[datetime] = None
        cursor: Optional[str] = None

        for _ in range(SLACK_HISTORY_MAX_PAGES):
            params: dict[str, Any] = {"channel": channel_id, "limit": SLACK_HISTORY_PAGE_LIMIT}
            if since is not None:
                params["oldest"] = _slack_ts_param(since)
            if cursor:
                params["cursor"] = cursor

            response = await _get_with_rate_limit_retry(
                client, f"{SLACK_API_BASE_URL}/conversations.history", headers, params
            )
            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict) or not payload.get("ok"):
                error = payload.get("error") if isinstance(payload, dict) else None
                logger.warning("slack_channel_history_read_failed", extra={"channel_id": channel_id, "error": error})
                return events, oldest_seen

            for message in _messages_from_payload(payload):
                if message.get("subtype") in IGNORED_SLACK_MESSAGE_SUBTYPES:
                    continue
                ts = first_non_empty_string(message.get("ts"))
                message_occurred_at = parse_slack_ts(ts) if ts is not None else None
                if message_occurred_at is None:
                    continue
                if oldest_seen is None or message_occurred_at < oldest_seen:
                    oldest_seen = message_occurred_at

                event = _message_event(message, channel_id, channel_name, connected_user_id)
                if event is None:
                    continue
                if since is not None and event.occurred_at <= since:
                    continue
                events.append(event)

            cursor = (payload.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return events, None

        logger.warning(
            "slack_channel_history_page_cap_reached",
            extra={"channel_id": channel_id, "max_pages": SLACK_HISTORY_MAX_PAGES},
        )
        return events, oldest_seen


def _messages_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get("messages")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []
