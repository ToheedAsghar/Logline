"""Groups unmatched remote events into reminders -- the last step of the Phase 4 pipeline, run after aggregation and
matching. A reminder is a factual nudge about unlogged activity, not a work-log entry.
"""

from dataclasses import dataclass
from datetime import date, timezone, tzinfo
from typing import Optional, Union

from app.matching.matcher import RemoteEventData


@dataclass(frozen=True)
class Reminder:
    """One factual nudge about unlogged remote activity.

    No hours/duration field -- the time behind these events was never measured, so none is invented here. `events`
    holds the original RemoteEventData objects unchanged, in their original order.
    """

    source: str
    remote_project_id: Optional[str]
    day: date
    events: list[RemoteEventData]


def generate_reminders(unmatched_events: list[RemoteEventData], tz: tzinfo = timezone.utc) -> list[Reminder]:
    """Group unmatched remote events into reminders, one per (source, project identity, day in `tz`).

    Groups by source, project, and day. When remote_project_id is None, groups by external_id instead, so unrelated
    project-less events don't get merged (mirrors matcher.py's rule that a missing identity never means "matches
    everything").

    Requires timezone-aware occurred_at; raises on naive input rather than silently guessing a timezone. Defaults to
    UTC.

    Returns groups in first-appearance order. Empty input returns an empty list.
    """

    grouped_events: dict[tuple[str, Union[str, None], date], list[RemoteEventData]] = {}
    group_order: list[tuple[str, Union[str, None], date]] = []

    for event in unmatched_events:
        if event.occurred_at.tzinfo is None:
            raise ValueError(
                f"generate_reminders requires timezone-aware occurred_at, but event {event.external_id!r} "
                f"(source={event.source!r}) has a naive datetime. Attach a tzinfo (e.g. timezone.utc) before "
                f"calling this function -- a naive datetime here would be silently misinterpreted as this "
                f"process's local time."
            )

        day = event.occurred_at.astimezone(tz).date()
        grouping_identity = event.remote_project_id if event.remote_project_id is not None else event.external_id
        key = (event.source, grouping_identity, day)
        if key not in grouped_events:
            grouped_events[key] = []
            group_order.append(key)
        grouped_events[key].append(event)

    reminders = []
    for source, grouping_identity, day in group_order:
        events = grouped_events[(source, grouping_identity, day)]
        reminders.append(Reminder(source=source, remote_project_id=events[0].remote_project_id, day=day, events=events))
    return reminders
