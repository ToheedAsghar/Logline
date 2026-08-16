"""Tests for the Stage 5 reconciliation call (app/agent/reconciliation/reconciler.py).

Runs entirely against a scripted fake `LLMProvider` -- the same pattern as test_llm_run_structured_default.py --
so the merge behaviour is observed against a known model response rather than a real one.

The central thing under test is the pre-built-reminder merge: pre-built reminders must survive the call
untouched, model reminders must survive it untouched, and neither may be dropped or duplicated. Pre-built
reminders are derived from `unmatched_events` (never accepted as a separate argument), so every test below
that wants a pre-built reminder gets one by including its underlying event in `unmatched_events`, not by
constructing a `Reminder` by hand.

`TestVerificationIsAttachedToTheResult` covers the Stage 5/Stage 6 wiring, whose one non-negotiable property is
that a draft failing verification still comes back in full. A scripted provider is what makes that testable at
all: it can return a draft broken in one exact way, which no real model can be relied on to do.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.agent.llm.base import LLMProvider, Message
from app.agent.reconciliation.prompt import SYSTEM_PROMPT
from app.agent.reconciliation.reconciler import (
    NOTE_LAST_RESORT, prebuilt_reminder_to_draft_reminder, reconcile_evidence,
)
from app.agent.reconciliation.schemas import (
    REMINDER_NOTE_MAX_LENGTH, BlockAllocation, DraftEntry, DraftReminder, EntryTag, WorkLogDraft,
    find_duration_language,
)
from app.local_activity.aggregation import LocalActivityBlock
from app.matching.matcher import MatchedGroup, RemoteEventData
from app.reminders.generator import Reminder

UTC = timezone.utc
DAY = date(2026, 7, 24)


def make_block(project="logline", start_hour=9, minutes=90):
    start = datetime(2026, 7, 24, start_hour, 0, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration, apps=["vscode"]
    )


def make_event(external_id="gh:pr:41", source="github", project="Toheed/logline", summary="Add schema", hour=9):
    return RemoteEventData(
        external_id=external_id,
        source=source,
        remote_project_id=project,
        occurred_at=datetime(2026, 7, 24, hour, 47, tzinfo=UTC),
        event_type="pull_request",
        summary=summary,
    )


def make_draft_entry(block_id=1, minutes=90, description="Worked on the reconciliation schema"):
    return DraftEntry(
        date=DAY,
        project="logline",
        allocations=[BlockAllocation(block_id=block_id, minutes=minutes)],
        tag=EntryTag.coding,
        description=description,
        source_remote_event_ids=["gh:pr:41"],
    )


def make_model_reminder(note="Which project did the unattributed block belong to?"):
    return DraftReminder(note=note, source="slack", day=DAY, source_remote_event_ids=["slack:msg:9"])


class ScriptedProvider(LLMProvider):
    """Returns a fixed draft and records exactly what it was asked."""

    def __init__(self, draft: WorkLogDraft):
        self.draft = draft
        self.calls: list[tuple[list[Message], type]] = []

    async def run_structured(self, messages, response_model):
        self.calls.append((messages, response_model))
        return self.draft


class ExplodingProvider(LLMProvider):
    def __init__(self, error: Exception):
        self.error = error

    async def run_structured(self, messages, response_model):
        raise self.error


class TestTheCallItself:
    @pytest.mark.asyncio
    async def test_calls_run_structured_with_the_system_prompt_and_the_worklogdraft_schema(self):
        provider = ScriptedProvider(WorkLogDraft())

        await reconcile_evidence([MatchedGroup(block=make_block(), events=[make_event()])], [], [], provider)

        assert len(provider.calls) == 1
        messages, response_model = provider.calls[0]
        assert response_model is WorkLogDraft
        assert [m.role for m in messages] == ["system", "user"]
        assert messages[0].content == SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_user_message_is_the_assembled_evidence(self):
        provider = ScriptedProvider(WorkLogDraft())

        await reconcile_evidence([], [make_block(project="logline", minutes=45)], [], provider)

        messages, _ = provider.calls[0]
        user_content = messages[1].content
        assert "block 1 |" in user_content
        assert "45 min measured" in user_content
        assert "project: logline" in user_content

    @pytest.mark.asyncio
    async def test_provider_errors_propagate_rather_than_being_swallowed_into_an_empty_draft(self):
        provider = ExplodingProvider(RuntimeError("upstream exploded"))

        with pytest.raises(RuntimeError, match="upstream exploded"):
            await reconcile_evidence([], [make_block()], [], provider)


class TestPrebuiltReminderMerge:
    @pytest.mark.asyncio
    async def test_the_reminders_built_note_text_is_not_sent_to_the_model(self):
        """The raw unmatched event legitimately appears in the evidence (the model needs to know not to
        re-raise it), but the reminder's synthesized note is only built after the model responds --
        `build_evidence` has no reminders parameter, so there is no path for that wording to reach the prompt.
        """
        event = make_event(external_id="ABC-99", source="jira", project="ABC", summary="Moved to Done")
        provider = ScriptedProvider(WorkLogDraft())

        result = await reconcile_evidence([], [make_block()], [event], provider)

        sent = "\n".join(m.content or "" for m in provider.calls[0][0])
        assert result.draft.reminders[0].note not in sent

    @pytest.mark.asyncio
    async def test_prebuilt_reminders_appear_in_the_returned_draft(self):
        event = make_event(external_id="ABC-99", source="jira", project="ABC")
        provider = ScriptedProvider(WorkLogDraft())

        draft = (await reconcile_evidence([], [make_block()], [event], provider)).draft

        assert len(draft.reminders) == 1
        assert draft.reminders[0].source == "jira"
        assert draft.reminders[0].source_remote_event_ids == ["ABC-99"]

    @pytest.mark.asyncio
    async def test_prebuilt_reminders_come_first_then_model_reminders_in_order(self):
        events = [make_event("ABC-1", "jira", project="ABC"), make_event("gh:pr:2")]
        model_reminders = [make_model_reminder("First model question?"), make_model_reminder("Second question?")]
        provider = ScriptedProvider(WorkLogDraft(reminders=model_reminders))

        draft = (await reconcile_evidence([], [make_block()], events, provider)).draft

        assert len(draft.reminders) == 4
        assert [r.source for r in draft.reminders[:2]] == ["jira", "github"]
        assert [r.note for r in draft.reminders[2:]] == ["First model question?", "Second question?"]

    @pytest.mark.asyncio
    async def test_model_reminders_survive_when_there_are_no_prebuilt_ones(self):
        model_reminder = make_model_reminder()
        provider = ScriptedProvider(WorkLogDraft(reminders=[model_reminder]))

        draft = (await reconcile_evidence([], [make_block()], [], provider)).draft

        assert draft.reminders == [model_reminder]

    @pytest.mark.asyncio
    async def test_no_reminder_is_duplicated_by_the_merge(self):
        event = make_event("ABC-1", "jira", project="ABC")
        provider = ScriptedProvider(WorkLogDraft(reminders=[make_model_reminder()]))

        draft = (await reconcile_evidence([], [make_block()], [event], provider)).draft

        notes = [r.note for r in draft.reminders]
        assert len(notes) == len(set(notes)) == 2

    @pytest.mark.asyncio
    async def test_empty_reminder_list_yields_a_draft_with_no_reminders(self):
        provider = ScriptedProvider(WorkLogDraft())

        draft = (await reconcile_evidence([], [make_block()], [], provider)).draft

        assert draft.reminders == []


class TestNothingElseFromTheModelIsDropped:
    @pytest.mark.asyncio
    async def test_entries_pass_through_unchanged(self):
        entries = [make_draft_entry(block_id=1, minutes=60), make_draft_entry(block_id=2, minutes=30)]
        provider = ScriptedProvider(WorkLogDraft(entries=entries))

        draft = (await reconcile_evidence([], [make_block(), make_block()], [], provider)).draft

        assert draft.entries == entries

    @pytest.mark.asyncio
    async def test_residual_unassigned_minutes_pass_through_unchanged(self):
        residual = [BlockAllocation(block_id=3, minutes=12)]
        provider = ScriptedProvider(WorkLogDraft(residual_unassigned_minutes=residual))

        draft = (await reconcile_evidence([], [make_block()], [], provider)).draft

        assert draft.residual_unassigned_minutes == residual

    @pytest.mark.asyncio
    async def test_a_fully_populated_draft_survives_the_merge_intact(self):
        entries = [make_draft_entry()]
        residual = [BlockAllocation(block_id=2, minutes=5)]
        model_reminder = make_model_reminder()
        provider = ScriptedProvider(
            WorkLogDraft(entries=entries, reminders=[model_reminder], residual_unassigned_minutes=residual)
        )
        event = make_event("ABC-1", "jira", project="ABC")

        draft = (await reconcile_evidence([], [make_block(), make_block()], [event], provider)).draft

        assert draft.entries == entries
        assert draft.residual_unassigned_minutes == residual
        assert draft.reminders[-1] == model_reminder
        assert len(draft.reminders) == 2


class TestVerificationIsAttachedToTheResult:
    """Stage 6 runs inside Stage 5, and its verdict rides along with the draft instead of replacing it."""

    @pytest.mark.asyncio
    async def test_a_correct_draft_comes_back_passed_with_no_issues(self):
        """One 90-minute block, fully allocated to one entry, citing the one event that was really in evidence."""
        entry = DraftEntry(
            date=DAY,
            project="logline",
            allocations=[BlockAllocation(block_id=1, minutes=90)],
            tag=EntryTag.coding,
            description="Worked on the reconciliation schema",
            source_remote_event_ids=["gh:pr:41"],
        )
        provider = ScriptedProvider(WorkLogDraft(entries=[entry]))

        result = await reconcile_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[make_event()])], [], [], provider
        )

        assert result.verification.passed is True
        assert result.verification.issues == []
        assert result.draft.entries == [entry]

    @pytest.mark.asyncio
    async def test_a_draft_citing_a_nonexistent_block_is_returned_rather_than_raising(self):
        """The headline guarantee: a broken draft is reported, not withheld and not turned into an exception."""
        entry = make_draft_entry(block_id=99, minutes=90)
        provider = ScriptedProvider(WorkLogDraft(entries=[entry]))

        result = await reconcile_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[make_event()])], [], [], provider
        )

        assert result.verification.passed is False
        assert result.draft.entries == [entry], "the draft must survive intact for the human who has to fix it"

        unknown = [i for i in result.verification.issues if i.check == "unknown_id" and i.block_id == 99]
        assert len(unknown) == 1
        assert unknown[0].severity == "error"

    @pytest.mark.asyncio
    async def test_the_real_underlying_error_is_reported_not_a_generic_failure(self):
        """A verification failure is only useful to a reviewer if it says which block and how far off it is."""
        entry = make_draft_entry(block_id=1, minutes=30)
        provider = ScriptedProvider(WorkLogDraft(entries=[entry]))

        result = await reconcile_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[make_event()])], [], [], provider
        )

        conservation = [i for i in result.verification.issues if i.check == "conservation"]
        assert len(conservation) == 1
        assert conservation[0].block_id == 1
        assert "30 min charged" in conservation[0].detail and "90 min measured" in conservation[0].detail

    @pytest.mark.asyncio
    async def test_verification_sees_the_merged_draft_not_the_raw_model_output(self):
        """The duplicate-reminder check only fires post-merge, so seeing it proves the ordering is right."""
        model_reminder = DraftReminder(
            note="Was the Jira transition part of this work?", source="jira", day=DAY,
            source_remote_event_ids=["ABC-99"],
        )
        provider = ScriptedProvider(WorkLogDraft(reminders=[model_reminder]))

        result = await reconcile_evidence([], [make_block(minutes=90)], [make_event("ABC-99", "jira")], provider)

        duplicates = [i for i in result.verification.issues if i.check == "duplicate_reminder"]
        assert len(duplicates) == 1
        assert "ABC-99" in duplicates[0].detail

    @pytest.mark.asyncio
    async def test_verification_uses_the_same_evidence_the_model_was_shown(self):
        """Block ids are assigned during evidence assembly; verifying against a re-derived set could differ."""
        entry = DraftEntry(
            date=DAY,
            project="logline",
            allocations=[BlockAllocation(block_id=2, minutes=45)],
            tag=EntryTag.coding,
            description="Second block only",
        )
        provider = ScriptedProvider(WorkLogDraft(entries=[entry]))

        result = await reconcile_evidence([], [make_block(minutes=90), make_block(minutes=45)], [], provider)

        # Block 2 is correctly allocated; only block 1 -- untouched by the draft -- should be complained about.
        assert {i.block_id for i in result.verification.issues} == {1}

    @pytest.mark.asyncio
    async def test_warnings_alone_do_not_fail_the_draft(self):
        residual = [BlockAllocation(block_id=1, minutes=30)]
        entry = DraftEntry(
            date=DAY,
            project="logline",
            allocations=[BlockAllocation(block_id=1, minutes=60)],
            tag=EntryTag.coding,
            description="Part of this block is attributable, part is not",
        )
        provider = ScriptedProvider(WorkLogDraft(entries=[entry], residual_unassigned_minutes=residual))

        result = await reconcile_evidence([], [make_block(minutes=90)], [], provider)

        assert result.verification.passed is True
        assert [i.severity for i in result.verification.issues] == ["warning"]

    @pytest.mark.asyncio
    async def test_a_failing_verification_triggers_no_second_call_to_the_model(self):
        """Auto-retry on failure is deliberately out of scope; this pins that it was not built in by accident."""
        provider = ScriptedProvider(WorkLogDraft(entries=[make_draft_entry(block_id=99)]))

        result = await reconcile_evidence([], [make_block(minutes=90)], [], provider)

        assert result.verification.passed is False
        assert len(provider.calls) == 1, "a failed verification must not silently re-prompt the model"

    @pytest.mark.asyncio
    async def test_nothing_in_the_draft_is_corrected_to_make_verification_pass(self):
        """Every field the model sent is still there afterwards, wrong values included."""
        entry = make_draft_entry(block_id=1, minutes=500)
        residual = [BlockAllocation(block_id=77, minutes=13)]
        provider = ScriptedProvider(WorkLogDraft(entries=[entry], residual_unassigned_minutes=residual))

        result = await reconcile_evidence([], [make_block(minutes=90)], [], provider)

        assert result.verification.passed is False
        assert result.draft.entries[0].allocations[0].minutes == 500
        assert result.draft.residual_unassigned_minutes == residual

    @pytest.mark.asyncio
    async def test_an_empty_draft_over_measured_time_fails_rather_than_passing_vacuously(self):
        """A model that returns nothing must not read as a clean result just because there is nothing to fault."""
        provider = ScriptedProvider(WorkLogDraft())

        result = await reconcile_evidence([], [make_block(minutes=90)], [], provider)

        assert result.verification.passed is False
        assert any(i.check == "completeness" for i in result.verification.issues)


class TestReminderConsistencyWithUnmatchedEvents:
    """The bug this guards against: `reconcile_evidence` used to accept `reminders` as an independent
    argument from `unmatched_events`, so nothing stopped a caller from passing reminders built from a
    different matcher run than the evidence. A reminder citing an event id the evidence never saw looks,
    to Stage 6, exactly like a fabricated citation -- it fails an otherwise-correct draft. Removing the
    parameter and deriving reminders from `unmatched_events` internally makes that construction impossible.
    """

    @pytest.mark.asyncio
    async def test_reconcile_evidence_no_longer_accepts_a_reminders_argument(self):
        """Pins the signature itself: there is no seam left for a caller to inject reminders from
        elsewhere. A TypeError here is not a bug in the test -- it is the fix.
        """
        import inspect

        params = inspect.signature(reconcile_evidence).parameters
        assert "reminders" not in params

    @pytest.mark.asyncio
    async def test_a_reminder_can_only_cite_an_event_present_in_the_evidence_it_ships_with(self):
        """Reproduces the original bug's failure mode directly: build a reminder from one event (as the
        old code allowed, sourced from a stale/different matcher run) and evidence from a different one,
        then confirm the merged draft's reminder can never cite an id verification would reject.

        Because `reconcile_evidence` derives reminders from `unmatched_events` itself, every reminder in
        the result necessarily cites only ids drawn from that same list -- the mismatch this test used to
        be able to construct by hand can no longer be expressed at all.
        """
        stale_event = make_event(external_id="stale:from-another-run", source="jira", project="ABC")
        current_event = make_event(external_id="ABC-99", source="jira", project="ABC")
        provider = ScriptedProvider(WorkLogDraft())

        result = await reconcile_evidence([], [], [current_event], provider)

        cited_ids = {
            event_id for reminder in result.draft.reminders for event_id in reminder.source_remote_event_ids
        }
        assert stale_event.external_id not in cited_ids
        assert cited_ids == {"ABC-99"}
        assert result.verification.passed is True
        unknown_id_issues = [i for i in result.verification.issues if i.check == "unknown_id"]
        assert unknown_id_issues == []


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
        events = [make_event(external_id=f"gh:pr:{i}", summary="A very long summary " * 10) for i in range(5)]
        reminder = Reminder(source="github", remote_project_id="Toheed/logline", day=DAY, events=events)

        note = prebuilt_reminder_to_draft_reminder(reminder).note

        assert len(note) <= REMINDER_NOTE_MAX_LENGTH

    def test_every_event_id_is_cited(self):
        events = [make_event(external_id=f"gh:pr:{i}") for i in range(3)]
        reminder = Reminder(source="github", remote_project_id="Toheed/logline", day=DAY, events=events)

        assert prebuilt_reminder_to_draft_reminder(reminder).source_remote_event_ids == [
            "gh:pr:0", "gh:pr:1", "gh:pr:2"
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
