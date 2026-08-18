"""Fetches calendar events from the Google Calendar REST API and normalizes them into events.

Filters out working location entries and declined invitations.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.remote_fetch.base import FetchedEvent, SourceCredentials, SourceFetchData, SourceFetcher
from app.remote_fetch.constants import MAX_EVENTS_PER_SOURCE
from app.remote_fetch.parsing import first_non_empty_string, parse_iso_datetime, to_utc_rfc3339

logger = logging.getLogger(__name__)

SOURCE = "calendar"
EVENT_TYPE_MEETING = "meeting"

GOOGLE_CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3"
PRIMARY_CALENDAR_ID = "primary"
WORKING_LOCATION_EVENT_TYPE = "workingLocation"
DECLINED_RESPONSE_STATUS = "declined"

CALENDAR_LIST_EVENTS_PAGE_SIZE = 250
# 2500 events per fetch before MAX_EVENTS_PER_SOURCE trims the result -- generous enough that a
# real user's window never hits it, and finite so a misbehaving API can't page forever.
CALENDAR_MAX_PAGES = 10


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

    async def fetch_with_client(
        self, client: httpx.AsyncClient, credentials: SourceCredentials, user_id: int, since: Optional[datetime]
    ) -> SourceFetchData:
        headers = {"Authorization": f"Bearer {credentials.access_token}"}
        now = datetime.now(timezone.utc)
        params: dict[str, Any] = {
            "timeMax": to_utc_rfc3339(now),
            "maxResults": CALENDAR_LIST_EVENTS_PAGE_SIZE,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        if since is not None:
            params["timeMin"] = to_utc_rfc3339(since)

        raw_events, hit_page_cap = await self._fetch_all_pages(client, headers, params)

        events: list[FetchedEvent] = []
        for raw_event in raw_events:
            event = _calendar_event(raw_event, PRIMARY_CALENDAR_ID)
            if event is not None:
                events.append(event)
        events.sort(key=lambda event: event.occurred_at)

        override = None
        if hit_page_cap:
            override = _event_time(raw_events[-1].get("start")) if raw_events else None
        if len(events) > MAX_EVENTS_PER_SOURCE:
            events = events[:MAX_EVENTS_PER_SOURCE]
            trimmed_override = events[-1].occurred_at
            override = trimmed_override if override is None else min(override, trimmed_override)

        return SourceFetchData(events=events, fetched_through_override=override)

    async def _fetch_all_pages(
        self, client: httpx.AsyncClient, headers: dict[str, str], params: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        """Follow `nextPageToken` up to CALENDAR_MAX_PAGES.

        Returns every raw event dict seen and whether the page cap was hit before pagination
        naturally exhausted (i.e. the raw fetch is known-incomplete).
        """

        raw_events: list[dict[str, Any]] = []
        page_token: Optional[str] = None
        hit_page_cap = False

        for _ in range(CALENDAR_MAX_PAGES):
            page_params = dict(params)
            if page_token:
                page_params["pageToken"] = page_token

            response = await client.get(
                f"{GOOGLE_CALENDAR_API_BASE_URL}/calendars/{PRIMARY_CALENDAR_ID}/events",
                headers=headers,
                params=page_params,
            )
            response.raise_for_status()
            payload = response.json()
            raw_events.extend(_events_from_payload(payload))

            page_token = payload.get("nextPageToken") if isinstance(payload, dict) else None
            if not page_token:
                break
        else:
            hit_page_cap = True
            logger.warning("calendar_hit_max_pages_without_exhausting_results", extra={"max_pages": CALENDAR_MAX_PAGES})

        return raw_events, hit_page_cap


def _events_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Extract raw event dicts from the events.list response."""

    if isinstance(payload, dict):
        items = payload.get("items") or []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    elif isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []
