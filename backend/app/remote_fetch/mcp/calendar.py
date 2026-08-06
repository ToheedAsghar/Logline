"""Fetches calendar events from Google Calendar and normalizes them into events.

Filters out working location entries and declined invitations.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from mcp import ClientSession

from app.remote_fetch.base import FetchedEvent, SourceFetchData, SourceFetcher
from app.remote_fetch.constants import CALENDAR_LIST_EVENTS_PAGE_SIZE, MAX_EVENTS_PER_SOURCE
from app.remote_fetch.mcp.connection import mcp_result_to_json
from app.remote_fetch.parsing import first_non_empty_string, parse_iso_datetime, to_naive_utc_isoformat

logger = logging.getLogger(__name__)

SOURCE = "calendar"
EVENT_TYPE_MEETING = "meeting"

PRIMARY_CALENDAR_ID = "primary"
WORKING_LOCATION_EVENT_TYPE = "workingLocation"

DECLINED_RESPONSE_STATUS = "declined"


def _event_time(value: Any) -> Optional[datetime]:
    """Parse start or end time from a Google Calendar event time payload."""

    if not isinstance(value, dict):
        return None
    return parse_iso_datetime(value.get("dateTime")) or parse_iso_datetime(value.get("date"))


def _self_declined(event: dict[str, Any]) -> bool:
    attendees = event.get("attendees")
    if not isinstance(attendees, list):
        return False
    return any(
        isinstance(attendee, dict)
        and attendee.get("self") is True
        and attendee.get("responseStatus") == DECLINED_RESPONSE_STATUS
        for attendee in attendees
    )


def _calendar_event(event: dict[str, Any], calendar_id: str) -> Optional[FetchedEvent]:
    """Build a meeting FetchedEvent from a Google Calendar event payload."""

    if event.get("eventType") == WORKING_LOCATION_EVENT_TYPE:
        return None
    if _self_declined(event):
        return None

    event_id = first_non_empty_string(event.get("id"))
    if event_id is None:
        return None

    occurred_at = _event_time(event.get("start"))
    if occurred_at is None:
        return None

    title = first_non_empty_string(event.get("summary"))
    attendees = event.get("attendees") if isinstance(event.get("attendees"), list) else []
    attendee_emails = [
        email
        for email in (
            first_non_empty_string(attendee.get("email"))
            for attendee in attendees
            if isinstance(attendee, dict)
        )
        if email
    ]

    summary = title or "(untitled event)"
    if attendee_emails:
        summary = f"{summary} ({len(attendee_emails)} attendees)"

    organizer = event.get("organizer") if isinstance(event.get("organizer"), dict) else {}
    end_at = _event_time(event.get("end"))

    return FetchedEvent(
        source=SOURCE,
        event_type=EVENT_TYPE_MEETING,
        external_id=event_id,
        occurred_at=occurred_at,
        summary=summary,
        description=first_non_empty_string(event.get("description")),
        remote_project_id=None,
        match_keys={
            "calendar_id": calendar_id,
            "attendees": attendee_emails,
            "organizer": first_non_empty_string(organizer.get("email")),
            "end_at": end_at.isoformat() if end_at else None,
        },
        raw_data=event,
    )


class CalendarFetcher(SourceFetcher):
    source = SOURCE

    async def fetch_with_session(
        self, session: ClientSession, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        now = datetime.now(timezone.utc)
        arguments: dict[str, Any] = {"calendarId": PRIMARY_CALENDAR_ID, "timeMax": to_naive_utc_isoformat(now)}
        if since is not None:
            arguments["timeMin"] = to_naive_utc_isoformat(since)

        result = await session.call_tool("list-events", arguments=arguments)
        payload = mcp_result_to_json(result)
        raw_events = _events_from_payload(payload)

        events: list[FetchedEvent] = []
        for raw_event in raw_events:
            event = _calendar_event(raw_event, PRIMARY_CALENDAR_ID)
            if event is not None:
                events.append(event)

        events.sort(key=lambda event: event.occurred_at)

        override = None
        api_may_be_truncated = len(raw_events) >= CALENDAR_LIST_EVENTS_PAGE_SIZE
        if api_may_be_truncated or len(events) > MAX_EVENTS_PER_SOURCE:
            if len(events) > MAX_EVENTS_PER_SOURCE:
                events = events[:MAX_EVENTS_PER_SOURCE]
            if events:
                override = events[-1].occurred_at
                logger.warning(
                    "calendar: list-events returned %d raw event(s) (this MCP tool exposes no "
                    "maxResults/pageToken to fetch more) -- holding the high-water mark at the "
                    "last event kept (%s) so the next run re-covers anything beyond it",
                    len(raw_events),
                    override.isoformat(),
                )

        return SourceFetchData(events=events, fetched_through_override=override)


def _events_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Extract raw event dicts from the list-events MCP response."""

    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("events") or []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    elif isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []
