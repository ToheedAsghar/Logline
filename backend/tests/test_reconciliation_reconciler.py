"""Test reconciliation orchestration, descriptions, reminders, and attached verification results."""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.agent.llm.base import LLMProvider, LLMStructuredOutputError, Message
from app.agent.reconciliation.reconciler import (
    MAX_CONCURRENT_DESCRIPTION_REQUESTS, NOTE_LAST_RESORT, prebuilt_reminder_to_draft_reminder, reconcile_evidence,
)
from app.agent.reconciliation.schemas import (
    DESCRIPTION_MAX_LENGTH, REMINDER_NOTE_MAX_LENGTH, EntryDescriptionProposal, EntryTag, TagSuggestion,
    find_duration_language,
)
from app.local_activity.aggregation import LocalActivityBlock
from app.local_activity.classification import SessionCategory
from app.matching.matcher import MatchedGroup, RemoteEventData
from app.reminders.generator import Reminder

UTC = timezone.utc
DAY = date(2026, 7, 24)


def make_block(project="logline", start_hour=9, minutes=90, category=SessionCategory.coding, meeting_name=None):
    start = datetime(2026, 7, 24, start_hour, 0, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration, apps=["vscode"],
        category=category, meeting_name=meeting_name,
    )


def make_event(external_id="logline#41", source="github", project="logline", summary="Add schema", hour=9):
    return RemoteEventData(
        external_id=external_id,
        source=source,
        remote_project_id=project,
        occurred_at=datetime(2026, 7, 24, hour, 47, tzinfo=UTC),
        event_type="pull_request",
        summary=summary,
    )


class ScriptedProvider(LLMProvider):
    """Returns a fixed `EntryDescriptionProposal` for every description call, and records every call."""

    def __init__(self, proposal: EntryDescriptionProposal | None = None):
        self.proposal = proposal or EntryDescriptionProposal(description="Worked on this entry.")
        self.calls: list[list[Message]] = []

    async def run_structured(self, messages, response_model):
        self.calls.append(messages)
        return self.proposal


class ExplodingProvider(LLMProvider):
    def __init__(self, error: Exception):
        self.error = error

    async def run_structured(self, messages, response_model):
        raise self.error


class ConcurrencyTrackingProvider(LLMProvider):
    """Records how many `run_structured` calls were ever simultaneously in flight."""

    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0

    async def run_structured(self, messages, response_model):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return EntryDescriptionProposal(description="ok")


class TestTheCallItself:
    @pytest.mark.asyncio
    async def test_one_provider_call_happens_per_non_meeting_entry(self):
        blocks = [make_block(project="logline", minutes=30), make_block(project="other-repo", minutes=20)]
        provider = ScriptedProvider()

        await reconcile_evidence([], blocks, [], provider)

        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_meeting_entries_never_call_the_provider(self):
        meeting = make_block(project=None, minutes=30, category=SessionCategory.meeting)
        provider = ScriptedProvider()

        event = make_event(external_id="cal:evt:1", source="calendar", summary="Design Review")
        await reconcile_evidence([MatchedGroup(block=meeting, events=[event])], [], [], provider)

        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_the_entrys_own_evidence_is_sent_not_the_whole_days(self):
        provider = ScriptedProvider()

        await reconcile_evidence([], [make_block(project="logline", minutes=45)], [], provider)

        sent = "\n".join(m.content or "" for m in provider.calls[0])
        assert "block 1 |" in sent
        assert "45 min measured" in sent
        assert "project: logline" in sent

    @pytest.mark.asyncio
    async def test_provider_errors_other_than_structured_output_error_propagate(self):
        """A gate violation or an LLMStructuredOutputError both fall back safely inside describe_entry; a raw,
        unexpected error is a different class of problem and must not be silently swallowed."""
        provider = ExplodingProvider(RuntimeError("upstream exploded"))

        with pytest.raises(RuntimeError, match="upstream exploded"):
            await reconcile_evidence([], [make_block()], [], provider)

    @pytest.mark.asyncio
    async def test_a_structured_output_error_does_not_propagate_it_falls_back_instead(self):
        provider = ExplodingProvider(LLMStructuredOutputError("truncated"))

        result = await reconcile_evidence([], [make_block()], [], provider)

        assert len(result.draft.entries) == 1
        assert result.draft.entries[0].description


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_description_requests_are_concurrent_and_bounded(self):
        provider = ConcurrencyTrackingProvider()
        blocks = [
            make_block(project=f"proj-{i}", start_hour=9 + i, minutes=10)
            for i in range(MAX_CONCURRENT_DESCRIPTION_REQUESTS + 3)
        ]

        await reconcile_evidence([], blocks, [], provider)

        assert provider.max_in_flight > 1
        assert provider.max_in_flight <= MAX_CONCURRENT_DESCRIPTION_REQUESTS


class TestMeetingEntriesAreDeterministic:
    @pytest.mark.asyncio
    async def test_description_is_the_calendar_events_title_verbatim(self):
        meeting = make_block(project=None, minutes=30, category=SessionCategory.meeting)
        event = make_event(external_id="cal:evt:1", source="calendar", summary="Team Standup Meeting")
        provider = ScriptedProvider()

        result = await reconcile_evidence([MatchedGroup(block=meeting, events=[event])], [], [], provider)

        assert result.draft.entries[0].description == "Team Standup Meeting"
        assert result.draft.entries[0].tag == EntryTag.meeting

    @pytest.mark.asyncio
    async def test_no_matched_event_and_no_tracked_name_falls_back_to_the_unidentified_label(self):
        meeting = make_block(project=None, minutes=30, category=SessionCategory.meeting)
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [meeting], [], provider)

        assert result.draft.entries[0].description == "Meeting (unidentified)"

    @pytest.mark.asyncio
    async def test_no_matched_event_uses_the_blocks_own_tracked_meeting_name(self):
        """The tracker captured the real Meet/Zoom name -- it beats the generic placeholder whenever it exists."""
        meeting = make_block(
            project=None, minutes=30, category=SessionCategory.meeting, meeting_name="Phase 4 Pipeline Sync"
        )
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [meeting], [], provider)

        assert result.draft.entries[0].description == "Phase 4 Pipeline Sync"

    @pytest.mark.asyncio
    async def test_a_matched_event_title_still_wins_over_the_tracked_meeting_name(self):
        meeting = make_block(
            project=None, minutes=30, category=SessionCategory.meeting, meeting_name="meet.google.com/abc-defg-hij"
        )
        event = make_event(external_id="cal:evt:1", source="calendar", summary="Team Standup Meeting")
        provider = ScriptedProvider()

        result = await reconcile_evidence([MatchedGroup(block=meeting, events=[event])], [], [], provider)

        assert result.draft.entries[0].description == "Team Standup Meeting"

    @pytest.mark.asyncio
    async def test_an_over_long_calendar_title_is_truncated_and_verifies(self):
        meeting = make_block(project=None, minutes=30, category=SessionCategory.meeting)
        event = make_event(external_id="cal:evt:1", source="calendar", summary="Planning " * 100)
        provider = ScriptedProvider()

        result = await reconcile_evidence([MatchedGroup(block=meeting, events=[event])], [], [], provider)

        description = result.draft.entries[0].description
        assert len(description) <= DESCRIPTION_MAX_LENGTH
        assert description.endswith("...")
        assert result.verification.passed

    @pytest.mark.asyncio
    async def test_calendar_title_with_duration_language_uses_safe_fallback_and_verifies(self):
        meeting = make_block(project=None, minutes=30, category=SessionCategory.meeting)
        event = make_event(external_id="cal:evt:1", source="calendar", summary="30 min planning sync")
        provider = ScriptedProvider()

        result = await reconcile_evidence([MatchedGroup(block=meeting, events=[event])], [], [], provider)

        assert result.draft.entries[0].description == "Meeting"
        assert result.verification.passed

    @pytest.mark.asyncio
    async def test_a_matched_event_without_a_title_falls_back_to_the_tracked_meeting_name(self):
        meeting = make_block(
            project=None, minutes=30, category=SessionCategory.meeting, meeting_name="Phase 4 Pipeline Sync"
        )
        event = make_event(external_id="cal:evt:1", source="calendar", summary=None)
        provider = ScriptedProvider()

        result = await reconcile_evidence([MatchedGroup(block=meeting, events=[event])], [], [], provider)

        assert result.draft.entries[0].description == "Phase 4 Pipeline Sync"

    @pytest.mark.asyncio
    async def test_a_whitespace_only_tracked_name_is_treated_as_absent(self):
        meeting = make_block(project=None, minutes=30, category=SessionCategory.meeting, meeting_name="   ")
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [meeting], [], provider)

        assert result.draft.entries[0].description == "Meeting (unidentified)"

    @pytest.mark.asyncio
    async def test_an_over_long_tracked_name_is_truncated_rather_than_failing_validation(self):
        """`DraftEntry.description` caps length -- an over-long window-title-derived name must not lose the entry."""
        meeting = make_block(
            project=None, minutes=30, category=SessionCategory.meeting, meeting_name="Sync " * 200
        )
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [meeting], [], provider)

        description = result.draft.entries[0].description
        assert len(description) <= DESCRIPTION_MAX_LENGTH
        assert description.endswith("...")

    @pytest.mark.asyncio
    async def test_multiple_matched_events_use_the_earliest_and_flag_review_reason(self):
        meeting = make_block(project=None, minutes=60, category=SessionCategory.meeting)
        later = make_event(external_id="cal:evt:2", source="calendar", summary="Later Title", hour=9)
        earlier = make_event(external_id="cal:evt:1", source="calendar", summary="Earlier Title", hour=8)
        provider = ScriptedProvider()

        result = await reconcile_evidence([MatchedGroup(block=meeting, events=[later, earlier])], [], [], provider)

        assert result.draft.entries[0].description == "Earlier Title"
        assert result.draft.entries[0].review_reason is not None


class TestEntryFormationFlowsIntoTheDraft:
    @pytest.mark.asyncio
    async def test_two_separate_projects_each_get_their_own_entry_and_description(self):
        provider = ScriptedProvider(EntryDescriptionProposal(description="Session description."))
        blocks = [make_block(project="logline", minutes=30), make_block(project="other-repo", minutes=20)]

        result = await reconcile_evidence([], blocks, [], provider)

        assert len(result.draft.entries) == 2
        assert all(entry.description == "Session description." for entry in result.draft.entries)

    @pytest.mark.asyncio
    async def test_work_that_reaches_an_entry_leaves_no_residual(self):
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [make_block(minutes=90)], [], provider)

        assert result.draft.residual_unassigned_minutes == []

    @pytest.mark.asyncio
    async def test_a_sub_floor_block_with_no_related_entry_becomes_residual(self):
        """A stray couple of minutes with nothing to fold into is reported rather than forced into unrelated work."""
        provider = ScriptedProvider()
        blocks = [
            make_block(project="logline", minutes=90, category=SessionCategory.coding),
            make_block(project="other-repo", minutes=2, category=SessionCategory.comms, start_hour=15),
        ]

        result = await reconcile_evidence([], blocks, [], provider)

        assert [allocation.minutes for allocation in result.draft.residual_unassigned_minutes] == [2]
        assert all(entry.allocations for entry in result.draft.entries)

    @pytest.mark.asyncio
    async def test_a_valid_tag_override_from_the_provider_is_used(self):
        proposal = EntryDescriptionProposal(
            description="Debugging a flaky test.",
            tag_suggestion=TagSuggestion(tag=EntryTag.debugging, reason="Evidence shows debugging"),
        )
        provider = ScriptedProvider(proposal)

        result = await reconcile_evidence([], [make_block(category=SessionCategory.coding)], [], provider)

        assert result.draft.entries[0].tag == EntryTag.debugging

    @pytest.mark.asyncio
    async def test_overlap_review_reason_from_entry_formation_survives_into_the_draft(self):
        meeting = make_block(project=None, start_hour=9, minutes=60, category=SessionCategory.meeting)
        coding = make_block(project="logline", start_hour=9, minutes=20, category=SessionCategory.coding)
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [meeting, coding], [], provider)

        coding_entry = next(e for e in result.draft.entries if e.tag == EntryTag.coding)
        assert coding_entry.review_reason is not None
        assert "Meeting" in coding_entry.review_reason


class TestPrebuiltReminderMerge:
    @pytest.mark.asyncio
    async def test_the_reminders_built_note_text_is_not_sent_to_the_model(self):
        """The raw unmatched event legitimately appears in the evidence (the model needs to know not to re-raise it),
        but the reminder's synthesized note is only built after the call -- `build_evidence` has no reminders parameter,
        so there is no path for that wording to reach the prompt."""
        event = make_event(external_id="ABC-99", source="jira", project="ABC", summary="Moved to Done")
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [make_block()], [event], provider)

        sent = "\n".join(m.content or "" for m in provider.calls[0])
        assert result.draft.reminders[0].note not in sent

    @pytest.mark.asyncio
    async def test_prebuilt_reminders_appear_in_the_returned_draft(self):
        event = make_event(external_id="ABC-99", source="jira", project="ABC")
        provider = ScriptedProvider()

        draft = (await reconcile_evidence([], [make_block()], [event], provider)).draft

        assert len(draft.reminders) == 1
        assert draft.reminders[0].source == "jira"
        assert draft.reminders[0].source_remote_event_ids == ["ABC-99"]

    @pytest.mark.asyncio
    async def test_multiple_prebuilt_reminders_preserve_generation_order(self):
        events = [make_event("ABC-1", "jira", project="ABC"), make_event("logline#2")]
        provider = ScriptedProvider()

        draft = (await reconcile_evidence([], [make_block()], events, provider)).draft

        assert len(draft.reminders) == 2
        assert [r.source for r in draft.reminders] == ["jira", "github"]

    @pytest.mark.asyncio
    async def test_empty_reminder_list_yields_a_draft_with_no_reminders(self):
        provider = ScriptedProvider()

        draft = (await reconcile_evidence([], [make_block()], [], provider)).draft

        assert draft.reminders == []


class TestVerificationIsAttachedToTheResult:
    """Stage 6 runs inside Stage 5, and its verdict rides along with the draft instead of replacing it."""

    @pytest.mark.asyncio
    async def test_a_normal_days_evidence_passes_verification_cleanly(self):
        provider = ScriptedProvider()

        result = await reconcile_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[make_event()])], [], [], provider
        )

        assert result.verification.passed is True
        assert result.verification.issues == []

    @pytest.mark.asyncio
    async def test_two_non_meeting_blocks_overlapping_is_still_caught_end_to_end(self):
        """Deterministic entry formation guarantees conservation and citations are correct by construction, so this is
        the one kind of problem that can still reach Stage 6 through this call: something wrong with the evidence itself
        (two non-meeting blocks whose time windows overlap, which a real matcher run should never produce) rather than
        with what entries.py or description.py did with it."""
        overlapping_a = make_block(project="logline", start_hour=9, minutes=60, category=SessionCategory.coding)
        overlapping_b = make_block(project="docs", start_hour=9, minutes=30, category=SessionCategory.code_review)
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [overlapping_a, overlapping_b], [], provider)

        assert result.verification.passed is False
        assert any(issue.check == "unexplained_overlap" for issue in result.verification.issues)


class TestReminderConsistencyWithUnmatchedEvents:
    """The bug this guards against: `reconcile_evidence` used to accept `reminders` as an independent argument from
    `unmatched_events`, so nothing stopped a caller from passing reminders built from a different matcher run than the
    evidence.

    A reminder citing an event id the evidence never saw looks, to Stage 6, exactly like a fabricated citation -- it
    fails an otherwise-correct draft. Removing the parameter and deriving reminders from `unmatched_events` internally
    makes that construction impossible.
    """

    @pytest.mark.asyncio
    async def test_reconcile_evidence_no_longer_accepts_a_reminders_argument(self):
        """Pins the signature itself: there is no seam left for a caller to inject reminders from elsewhere.

        A TypeError here is not a bug in the test -- it is the fix.
        """
        import inspect

        params = inspect.signature(reconcile_evidence).parameters
        assert "reminders" not in params

    @pytest.mark.asyncio
    async def test_a_reminder_can_only_cite_an_event_present_in_the_evidence_it_ships_with(self):
        stale_event = make_event(external_id="stale:from-another-run", source="jira", project="ABC")
        current_event = make_event(external_id="ABC-99", source="jira", project="ABC")
        provider = ScriptedProvider()

        result = await reconcile_evidence([], [], [current_event], provider)

        cited_ids = {
            event_id for reminder in result.draft.reminders for event_id in reminder.source_remote_event_ids
        }
        assert stale_event.external_id not in cited_ids
        assert cited_ids == {"ABC-99"}
        assert result.verification.passed is True
        unknown_id_issues = [i for i in result.verification.issues if i.check == "unknown_id"]
        assert unknown_id_issues == []

    @pytest.mark.asyncio
    async def test_event_matched_only_to_a_zero_rounded_block_becomes_a_reminder(self):
        event = make_event(external_id="ABC-99", source="jira", project="ABC")
        provider = ScriptedProvider()

        result = await reconcile_evidence(
            [MatchedGroup(block=make_block(minutes=0), events=[event])], [], [], provider
        )

        assert [reminder.source_remote_event_ids for reminder in result.draft.reminders] == [["ABC-99"]]
        assert result.verification.passed


class TestPrebuiltReminderConversion:
    def test_summaries_are_included_when_they_are_clean(self):
        reminder = Reminder(
            source="github",
            remote_project_id="Toheed/logline",
            day=DAY,
            events=[make_event(summary="Add reconciliation schema")],
        )

        assert "Add reconciliation schema" in prebuilt_reminder_to_draft_reminder(reminder).note

    def test_summary_containing_duration_language_is_dropped_instead_of_raising(self):
        """A real PR title can read as a duration; that must not take down the whole reconciliation."""
        reminder = Reminder(
            source="github",
            remote_project_id="Toheed/logline",
            day=DAY,
            events=[make_event(summary="Cut build time by 30 minutes")],
        )

        note = prebuilt_reminder_to_draft_reminder(reminder).note

        assert "30 minutes" not in note
        assert find_duration_language(note) is None
        assert "Toheed/logline" in note

    def test_falls_back_to_a_fixed_note_when_the_project_name_itself_reads_as_a_duration(self):
        reminder = Reminder(
            source="github",
            remote_project_id="team/spent-90-minutes-repo",
            day=DAY,
            events=[make_event(summary="Cut build time by 30 minutes")],
        )

        note = prebuilt_reminder_to_draft_reminder(reminder).note

        assert note == NOTE_LAST_RESORT
        assert find_duration_language(note) is None

    def test_missing_project_identity_is_described_rather_than_rendered_as_none(self):
        reminder = Reminder(
            source="calendar",
            remote_project_id=None,
            day=DAY,
            events=[make_event(external_id="cal:evt:7", source="calendar", project=None, summary="Sync")],
        )

        note = prebuilt_reminder_to_draft_reminder(reminder).note

        assert "None" not in note
        assert "unidentified" in note

    def test_long_summaries_are_truncated_to_the_schema_limit(self):
        events = [make_event(external_id=f"logline#{i}", summary="A very long summary " * 10) for i in range(5)]
        reminder = Reminder(source="github", remote_project_id="Toheed/logline", day=DAY, events=events)

        note = prebuilt_reminder_to_draft_reminder(reminder).note

        assert len(note) <= REMINDER_NOTE_MAX_LENGTH

    def test_every_event_id_is_cited(self):
        events = [make_event(external_id=f"logline#{i}") for i in range(3)]
        reminder = Reminder(source="github", remote_project_id="Toheed/logline", day=DAY, events=events)

        assert prebuilt_reminder_to_draft_reminder(reminder).source_remote_event_ids == [
            "logline#0", "logline#1", "logline#2"
        ]

    def test_day_is_carried_over_unchanged(self):
        reminder = Reminder(source="github", remote_project_id="x", day=date(2026, 1, 2), events=[make_event()])

        assert prebuilt_reminder_to_draft_reminder(reminder).day == date(2026, 1, 2)

    def test_a_source_the_draft_schema_cannot_model_is_rejected_with_a_clear_error(self):
        reminder = Reminder(source="gitlab", remote_project_id="x", day=DAY, events=[make_event(source="gitlab")])

        with pytest.raises(ValueError, match="gitlab"):
            prebuilt_reminder_to_draft_reminder(reminder)

    @pytest.mark.parametrize("source", ["github", "jira", "slack", "calendar"])
    def test_all_four_modelled_sources_convert(self, source):
        reminder = Reminder(source=source, remote_project_id="x", day=DAY, events=[make_event(source=source)])

        assert prebuilt_reminder_to_draft_reminder(reminder).source == source
