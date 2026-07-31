"""
Tests for generate_reminders (app/reminders/generator.py), the last step of the Phase 4 pipeline: turning unmatched
remote events into factual reminders instead of guessed work-log entries.

Pure logic, no I/O -- every case runs entirely against in-memory RemoteEventData fixtures, the same type
app/matching/matcher.py already produces. Coverage follows the grouping rule, the None-project edge case, the `tz`
parameter's effect on calendar day, and the one thing that must never happen: an hours/duration field on Reminder.

No real LLM/MCP/database calls are made anywhere in this file.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.matching.matcher import RemoteEventData
from app.reminders.generator import Reminder, generate_reminders

LOGLINE_REPO = "ToheedAsghar/Logline"
OTHER_REPO = "ToheedAsghar/other-repo"

PKT = timezone(timedelta(hours=5))


def _at(day_offset: int = 0, minute_offset: int = 0) -> datetime:
    return datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc) + timedelta(days=day_offset, minutes=minute_offset)


def _event(
    external_id: str,
    source: str = "github",
    remote_project_id: str | None = LOGLINE_REPO,
    day_offset: int = 0,
    minute_offset: int = 0,
    event_type: str = "commit",
    summary: str = "fix: resolve off-by-one in aggregation",
    occurred_at: datetime | None = None,
) -> RemoteEventData:
    return RemoteEventData(
        external_id=external_id,
        source=source,
        remote_project_id=remote_project_id,
        occurred_at=occurred_at if occurred_at is not None else _at(day_offset, minute_offset),
        event_type=event_type,
        summary=summary,
    )


class TestSingleEvent:
    def test_single_unmatched_event_produces_one_reminder(self):
        event = _event("sha-1")

        reminders = generate_reminders([event])

        assert reminders == [
            Reminder(source="github", remote_project_id=LOGLINE_REPO, day=date(2026, 7, 24), events=[event])
        ]


class TestGroupingSameProjectSameDay:
    def test_multiple_events_same_source_project_and_day_group_into_one_reminder(self):
        events = [
            _event("sha-1", minute_offset=0),
            _event("sha-2", minute_offset=30),
            _event("sha-3", minute_offset=90),
        ]

        reminders = generate_reminders(events)

        assert len(reminders) == 1
        assert reminders[0].events == events

    def test_grouped_reminder_keeps_events_in_original_order(self):
        events = [
            _event("sha-3", minute_offset=90),
            _event("sha-1", minute_offset=0),
            _event("sha-2", minute_offset=30),
        ]

        reminders = generate_reminders(events)

        assert reminders[0].events == events


class TestNeverGroupedTogether:
    """Different project, source, or day must never be folded into the same reminder -- merging would blur separate
    pieces of evidence into one guess."""

    def test_different_projects_stay_separate(self):
        logline_event = _event("sha-1", remote_project_id=LOGLINE_REPO)
        other_event = _event("sha-2", remote_project_id=OTHER_REPO)

        reminders = generate_reminders([logline_event, other_event])

        assert len(reminders) == 2
        assert reminders[0].events == [logline_event]
        assert reminders[1].events == [other_event]

    def test_different_sources_stay_separate_even_for_same_project(self):
        commit = _event("sha-1", source="github", event_type="commit")
        transition = _event("LOG-42", source="jira", event_type="transition")

        reminders = generate_reminders([commit, transition])

        assert len(reminders) == 2
        assert reminders[0].source == "github"
        assert reminders[1].source == "jira"

    def test_different_days_stay_separate_even_for_same_project_and_source(self):
        today_event = _event("sha-1", day_offset=0)
        yesterday_event = _event("sha-2", day_offset=-1)

        reminders = generate_reminders([yesterday_event, today_event])

        assert len(reminders) == 2
        assert reminders[0].day == date(2026, 7, 23)
        assert reminders[1].day == date(2026, 7, 24)


class TestEmptyInput:
    def test_empty_input_returns_empty_list(self):
        assert generate_reminders([]) == []


class TestNoInventedTime:
    """Reminder must never carry an hours/duration field, under any name -- time here is never invented."""

    def test_reminder_has_no_duration_or_hours_field(self):
        reminder = generate_reminders([_event("sha-1")])[0]

        field_names = {f for f in vars(reminder)}
        forbidden = {"hours", "duration", "estimated_hours", "time_spent"}

        assert field_names.isdisjoint(forbidden)

    def test_reminder_fields_are_exactly_source_project_day_events(self):
        reminder = generate_reminders([_event("sha-1")])[0]

        assert set(vars(reminder).keys()) == {"source", "remote_project_id", "day", "events"}


class TestSummaryReuse:
    def test_reminder_reuses_event_summary_verbatim_not_regenerated(self):
        event = _event("sha-1", summary="feat: add retry logic to webhook handler")

        reminder = generate_reminders([event])[0]

        assert reminder.events[0].summary == "feat: add retry logic to webhook handler"

    def test_reminder_preserves_external_id_for_finding_real_evidence(self):
        event = _event("sha-abc123")

        reminder = generate_reminders([event])[0]

        assert reminder.events[0].external_id == "sha-abc123"


class TestNoneProjectDoesNotCollide:
    """remote_project_id=None must not act as a shared bucket -- unrelated None-project events must land in separate
    reminders, not merge into one."""

    def test_two_unrelated_none_project_events_produce_two_separate_reminders(self):
        dentist = _event(
            "cal-evt-1",
            source="calendar",
            remote_project_id=None,
            event_type="calendar_event",
            summary="Dentist appointment",
            minute_offset=0,
        )
        sprint_planning = _event(
            "cal-evt-2",
            source="calendar",
            remote_project_id=None,
            event_type="calendar_event",
            summary="Sprint planning",
            minute_offset=60,
        )

        reminders = generate_reminders([dentist, sprint_planning])

        assert len(reminders) == 2
        assert reminders[0].events == [dentist]
        assert reminders[1].events == [sprint_planning]
        assert reminders[0].remote_project_id is None
        assert reminders[1].remote_project_id is None

    def test_none_project_event_still_groups_with_itself_via_external_id(self):
        event = _event("cal-evt-1", source="calendar", remote_project_id=None, event_type="calendar_event")

        reminders = generate_reminders([event, event])

        assert len(reminders) == 1
        assert reminders[0].events == [event, event]


class TestTimezoneParameter:
    """`tz` controls which calendar day an event's occurred_at lands under. Defaults to UTC so existing callers are
    unaffected; occurred_at must be timezone-aware since astimezone() would otherwise silently treat a naive datetime as
    this process's local time."""

    def test_default_tz_is_utc_and_matches_pre_fix_behavior(self):
        event = _event("sha-1", occurred_at=datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc))

        reminders = generate_reminders([event])

        assert reminders[0].day == date(2026, 7, 24)

    def test_early_morning_pkt_event_does_not_land_on_utc_calendar_day(self):
        # 2026-07-24 03:00 PKT (UTC+5) is 2026-07-23 22:00 UTC -- the UTC calendar day is one behind.
        event = _event("sha-1", occurred_at=datetime(2026, 7, 24, 3, 0, tzinfo=PKT))

        utc_reminders = generate_reminders([event])
        pkt_reminders = generate_reminders([event], tz=PKT)

        assert utc_reminders[0].day == date(2026, 7, 23)
        assert pkt_reminders[0].day == date(2026, 7, 24)

    def test_naive_occurred_at_raises_clear_error_instead_of_silently_misbehaving(self):
        naive_event = _event("sha-1", occurred_at=datetime(2026, 7, 24, 9, 0))

        with pytest.raises(ValueError, match="timezone-aware"):
            generate_reminders([naive_event])
