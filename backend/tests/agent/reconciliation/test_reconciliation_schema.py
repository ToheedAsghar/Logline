"""Constraint tests for Stage 5 reconciliation schema validation and duration detection."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.agent.reconciliation.schemas import (
    DESCRIPTION_MAX_LENGTH, MINUTES_PER_DAY, REMINDER_NOTE_MAX_LENGTH, REVIEW_REASON_MAX_LENGTH, BlockAllocation,
    DraftEntry, DraftReminder, EntryTag, WorkLogDraft, find_duration_language, truncate_description,
)

CANONICAL_TAGS = {
    "Training/Learning", "Coding", "R&D", "Team Engagement", "Testing", "Meeting", "Designing",
    "Code Review", "Debugging", "Documentation", "Backlog grooming", "Technical Project Setup",
    "Coordination", "Project Planning", "Team Management", "Tech Assessment", "Interviewing",
    "Architecture Design", "Reporting/Analysis", "Presenting", "Course Authoring", "Support Tickets",
    "Reviews", "Deployment", "Support", "Project Estimations", "Account Management", "Recruiting",
    "Operations", "Capex", "Opex", "Customer Implementation", "Marketing Campaigns",
    "Sales/Client Demo", "Audit/Compliance", "Other",
}


def valid_entry(**overrides) -> dict:
    base = {
        "date": date(2026, 7, 24),
        "project": "Logline",
        "allocations": [{"block_id": 1, "minutes": 45}],
        "tag": EntryTag.coding,
        "description": "Implemented the reconciliation output schema.",
        "source_remote_event_ids": ["gh:pr:41"],
        "review_reason": None,
    }
    return {**base, **overrides}


def valid_reminder(**overrides) -> dict:
    base = {
        "note": "Was the deploy pipeline work part of the Logline project?",
        "source": "github",
        "day": date(2026, 7, 24),
        "source_remote_event_ids": ["gh:pr:41"],
    }
    return {**base, **overrides}


def test_truncate_description_preserves_complete_words_when_possible():
    text = "complete " * 40

    truncated = truncate_description(text)

    assert len(truncated) <= DESCRIPTION_MAX_LENGTH
    assert truncated.endswith("...")
    assert set(truncated.removesuffix("...").split()) == {"complete"}


def test_all_36_tags_present_and_exact():
    values = [tag.value for tag in EntryTag]
    assert len(values) == 36
    assert len(set(values)) == 36, "duplicate tag values"
    assert set(values) == CANONICAL_TAGS


def test_other_is_pinned_last():
    assert list(EntryTag)[-1] is EntryTag.other


def test_high_frequency_tags_lead_the_enum():
    """Verify that high-frequency tags lead the enum ordering to minimize prompt position bias."""
    leading = [tag.value for tag in list(EntryTag)[:6]]
    assert leading == ["Coding", "Debugging", "Code Review", "Meeting", "Testing", "Documentation"]


@pytest.mark.parametrize("tag_value", sorted(CANONICAL_TAGS))
def test_every_tag_is_accepted_by_value(tag_value):
    entry = DraftEntry.model_validate(valid_entry(tag=tag_value))
    assert entry.tag.value == tag_value


def test_unknown_tag_is_rejected():
    with pytest.raises(ValidationError):
        DraftEntry.model_validate(valid_entry(tag="Napping"))


@pytest.mark.parametrize("minutes", [0, -1, -60])
def test_minutes_must_be_positive(minutes):
    with pytest.raises(ValidationError) as exc:
        BlockAllocation(block_id=1, minutes=minutes)
    assert "minutes" in str(exc.value)


def test_minutes_accepts_one():
    assert BlockAllocation(block_id=1, minutes=1).minutes == 1


def test_minutes_accepts_the_ceiling_exactly():
    """Verify that MINUTES_PER_DAY is accepted at the inclusive upper boundary."""
    assert BlockAllocation(block_id=1, minutes=MINUTES_PER_DAY).minutes == 1440


@pytest.mark.parametrize("minutes", [MINUTES_PER_DAY + 1, 100_000])
def test_minutes_above_the_ceiling_rejected(minutes):
    with pytest.raises(ValidationError) as exc:
        BlockAllocation(block_id=1, minutes=minutes)
    assert "minutes" in str(exc.value)


def test_absurd_minutes_rejected_inside_an_entry():
    """Verify that the minutes upper ceiling is enforced within nested entry allocations."""
    with pytest.raises(ValidationError):
        DraftEntry.model_validate(valid_entry(allocations=[{"block_id": 7, "minutes": 100_000}]))


def test_absurd_minutes_rejected_in_residual():
    with pytest.raises(ValidationError):
        WorkLogDraft.model_validate(
            {"residual_unassigned_minutes": [{"block_id": 9, "minutes": MINUTES_PER_DAY + 1}]}
        )


def test_allocation_forbids_a_bare_hours_field():
    """Verify that extra unmeasured fields like 'hours' are rejected."""
    with pytest.raises(ValidationError):
        BlockAllocation.model_validate({"block_id": 1, "minutes": 30, "hours": 4})


@pytest.mark.parametrize("block_id", [0, -1, -99])
def test_block_id_must_be_positive(block_id):
    """Verify that block_id is rejected at or below zero — real measured block IDs start at 1."""
    with pytest.raises(ValidationError) as exc:
        BlockAllocation(block_id=block_id, minutes=30)
    assert "block_id" in str(exc.value)


def test_block_id_accepts_one():
    assert BlockAllocation(block_id=1, minutes=30).block_id == 1


def test_nonpositive_block_id_rejected_inside_an_entry():
    with pytest.raises(ValidationError):
        DraftEntry.model_validate(valid_entry(allocations=[{"block_id": 0, "minutes": 30}]))


def test_nonpositive_block_id_rejected_in_residual():
    with pytest.raises(ValidationError):
        WorkLogDraft.model_validate({"residual_unassigned_minutes": [{"block_id": -3, "minutes": 30}]})


def test_duplicate_block_id_rejected_within_an_entry():
    """Verify that charging one block twice in a single entry is rejected as double-counted time."""
    with pytest.raises(ValidationError) as exc:
        DraftEntry.model_validate(
            valid_entry(allocations=[{"block_id": 4, "minutes": 30}, {"block_id": 4, "minutes": 45}])
        )
    assert "block_id 4" in str(exc.value)


def test_duplicate_block_id_rejected_even_with_identical_minutes():
    """Verify detection does not depend on the minutes differing — uniqueItems would miss this case."""
    with pytest.raises(ValidationError):
        DraftEntry.model_validate(
            valid_entry(allocations=[{"block_id": 4, "minutes": 30}, {"block_id": 4, "minutes": 30}])
        )


def test_distinct_block_ids_accepted_within_an_entry():
    entry = DraftEntry.model_validate(
        valid_entry(allocations=[{"block_id": 4, "minutes": 30}, {"block_id": 5, "minutes": 45}])
    )
    assert [a.block_id for a in entry.allocations] == [4, 5]


def test_duplicate_block_id_rejected_in_residual():
    with pytest.raises(ValidationError) as exc:
        WorkLogDraft.model_validate(
            {"residual_unassigned_minutes": [{"block_id": 9, "minutes": 4}, {"block_id": 9, "minutes": 6}]}
        )
    assert "residual_unassigned_minutes" in str(exc.value)


def test_same_block_may_appear_in_two_different_entries():
    """Verify the uniqueness rule is per-list — one block legitimately splits across two entries."""
    draft = WorkLogDraft.model_validate(
        {
            "entries": [
                valid_entry(allocations=[{"block_id": 1, "minutes": 30}]),
                valid_entry(project="Atlas", allocations=[{"block_id": 1, "minutes": 15}]),
            ]
        }
    )
    assert [a.block_id for e in draft.entries for a in e.allocations] == [1, 1]


def test_empty_allocations_rejected():
    with pytest.raises(ValidationError) as exc:
        DraftEntry.model_validate(valid_entry(allocations=[]))
    assert "allocations" in str(exc.value)


def test_single_allocation_accepted():
    entry = DraftEntry.model_validate(valid_entry(allocations=[{"block_id": 7, "minutes": 15}]))
    assert len(entry.allocations) == 1


def test_zero_minute_allocation_rejected_inside_an_entry():
    with pytest.raises(ValidationError):
        DraftEntry.model_validate(valid_entry(allocations=[{"block_id": 7, "minutes": 0}]))


def test_description_at_limit_accepted():
    entry = DraftEntry.model_validate(valid_entry(description="x" * DESCRIPTION_MAX_LENGTH))
    assert len(entry.description) == DESCRIPTION_MAX_LENGTH


def test_description_over_limit_rejected():
    with pytest.raises(ValidationError) as exc:
        DraftEntry.model_validate(valid_entry(description="x" * (DESCRIPTION_MAX_LENGTH + 1)))
    assert "description" in str(exc.value)


def test_entry_allows_zero_remote_events():
    """Verify that entries accept empty remote event lists for local-only work."""
    entry = DraftEntry.model_validate(valid_entry(source_remote_event_ids=[]))
    assert entry.source_remote_event_ids == []


def test_review_reason_is_optional_but_expressible():
    assert DraftEntry.model_validate(valid_entry(review_reason=None)).review_reason is None
    flagged = DraftEntry.model_validate(valid_entry(review_reason="Two projects share this block."))
    assert flagged.review_reason == "Two projects share this block."


@pytest.mark.parametrize("source", ["github", "jira", "slack", "calendar"])
def test_valid_reminder_sources_accepted(source):
    assert DraftReminder.model_validate(valid_reminder(source=source)).source == source


@pytest.mark.parametrize("source", ["gitlab", "email", "GitHub", "", "local"])
def test_invalid_reminder_sources_rejected(source):
    with pytest.raises(ValidationError) as exc:
        DraftReminder.model_validate(valid_reminder(source=source))
    assert "source" in str(exc.value)


DURATION_BEARING_NOTES = [
    "Did you work 2 hours on the auth refactor?",
    "You spent 45 min reviewing this PR.",
    "This looks like 1.5hrs of debugging.",
    "Roughly 30m of Slack coordination here.",
    "Was this 1h30 of pairing?",
    "Did you spend two hours on the migration?",
    "A few minutes of triage, correct?",
    "Half an hour on the incident?",
    "How long did you spend on this ticket?",
    "You worked on this for about the whole standup.",
    "The review took roughly the same as yesterday.",
    "Were you in meetings all day Tuesday?",
    "Most of the morning went to code review, right?",
    "Was that the 2-hour architecture sync?",
    "Did the 90-minute workshop cover Logline?",
    "Was this the 30-min triage call?",
    "A 45-min pairing session on the parser?",
    "Was it eleven minutes of CI babysitting?",
    "Did fifteen minutes go to the flaky test?",
    "Was twenty minutes of that the standup?",
    "Did forty-five minutes go to code review?",
    "Was ninety minutes of this the migration?",
    "Did twenty-five minutes go to Slack?",
    "Was seventy minutes of that debugging?",
    "How long was the incident call?",
    "How long did the deploy take?",
    "How much time went to the Atlas migration?",
    "Were you in workshops all morning?",
    "Did the entire afternoon go to interviews?",
    "Did the whole evening go to the release?",
    "Did the rest of the day go to Logline?",
    "Was half a day on the migration?",
    "Did a full day go to onboarding?",
    "Was half the morning on code review?",
    "Did 3 days go to the Atlas rollout?",
    "Was that two days of migration work?",
]


@pytest.mark.parametrize("note", DURATION_BEARING_NOTES)
def test_duration_bearing_notes_rejected(note):
    assert find_duration_language(note) is not None, "detector missed a duration"
    with pytest.raises(ValidationError) as exc:
        DraftReminder.model_validate(valid_reminder(note=note))
    assert "duration" in str(exc.value)


LEGITIMATE_NOTES = [
    "PR #123 needs review — was that Logline work?",
    "Ticket ABC-4821 was moved to Done. Which project?",
    "Was your 14:30 standup work-related?",
    "Was this about the caching bug?",
    "You worked around the flaky test — which project was that for?",
    "Who took over the deploy on 2026-07-14?",
    "Was the thread in #logline-dev project work?",
    "Commit a1b2c3d landed on main — which project?",
    "Was the 9:00 to 9:30 slot on your calendar work?",
    "Sprint 12 planning — was that Logline or Atlas?",
    "Was the ad spend review Marketing Campaigns work?",
    "Which client does the marketing spend belong to?",
    "Was this media spend work or Account Management?",
    "The total spend report — was that for Atlas?",
]


@pytest.mark.parametrize("note", LEGITIMATE_NOTES)
def test_legitimate_notes_accepted(note):
    assert find_duration_language(note) is None, f"false positive on: {note}"
    reminder = DraftReminder.model_validate(valid_reminder(note=note))
    assert reminder.note == note


@pytest.mark.parametrize(
    "note",
    [
        "Did you spend the morning on Atlas?",
        "How much time did you spend there?",
        "Were you spending time on the parser?",
        "You spent that block on code review.",
    ],
)
def test_verbal_spend_still_rejected(note):
    """Verify the noun-'spend' fix did not stop the detector catching genuinely verbal uses."""
    assert find_duration_language(note) is not None


@pytest.mark.parametrize("note", ["Was your 14:30 standup work-related?", "Was the 9:00 to 9:30 slot work?"])
def test_colon_clock_times_are_not_duration_language(note):
    """Verify colon-format clock times name a point in time, not an amount, and are accepted."""
    assert find_duration_language(note) is None


def test_european_hmm_clock_format_is_matched_as_documented():
    """The '14h30' shape is indistinguishable from the duration '1h30'; the docstring documents that it matches."""
    assert find_duration_language("Was your 14h30 standup work-related?") is not None


def test_detector_labels_what_it_matched():
    """Verify that find_duration_language returns a non-empty pattern label on match."""
    label = find_duration_language("spent 2 hours")
    assert label is not None and label.strip()


def test_empty_note_rejected():
    with pytest.raises(ValidationError):
        DraftReminder.model_validate(valid_reminder(note=""))


def build_full_draft() -> WorkLogDraft:
    return WorkLogDraft(
        entries=[
            DraftEntry.model_validate(valid_entry()),
            DraftEntry.model_validate(
                valid_entry(
                    project="Atlas",
                    tag=EntryTag.code_review,
                    allocations=[{"block_id": 2, "minutes": 20}, {"block_id": 3, "minutes": 10}],
                    source_remote_event_ids=[],
                    review_reason="Block 3 straddles two projects.",
                )
            ),
        ],
        reminders=[DraftReminder.model_validate(valid_reminder())],
        residual_unassigned_minutes=[BlockAllocation(block_id=9, minutes=4)],
    )


def test_full_draft_round_trip():
    draft = build_full_draft()
    dumped = draft.model_dump()
    assert WorkLogDraft.model_validate(dumped) == draft


def test_full_draft_json_round_trip():
    """Verify JSON serialization and deserialization round-trip for WorkLogDraft."""
    draft = build_full_draft()
    assert WorkLogDraft.model_validate_json(draft.model_dump_json()) == draft


def test_round_trip_preserves_time_exactly():
    draft = build_full_draft()
    restored = WorkLogDraft.model_validate(draft.model_dump())
    original = [(a.block_id, a.minutes) for e in draft.entries for a in e.allocations]
    survived = [(a.block_id, a.minutes) for e in restored.entries for a in e.allocations]
    assert survived == original
    assert restored.residual_unassigned_minutes[0].minutes == 4


def test_empty_draft_is_valid():
    """Verify that an unpopulated WorkLogDraft is valid."""
    draft = WorkLogDraft()
    assert draft.entries == [] and draft.reminders == [] and draft.residual_unassigned_minutes == []


def test_residual_minutes_also_reject_zero():
    with pytest.raises(ValidationError):
        WorkLogDraft.model_validate({"residual_unassigned_minutes": [{"block_id": 9, "minutes": 0}]})


@pytest.mark.parametrize(
    ("model", "payload", "smuggled"),
    [
        (BlockAllocation, {"block_id": 1, "minutes": 30}, "hours"),
        (BlockAllocation, {"block_id": 1, "minutes": 30}, "total_minutes"),
        (DraftEntry, valid_entry(), "hours"),
        (DraftEntry, valid_entry(), "total_minutes"),
        (DraftReminder, valid_reminder(), "hours"),
        (DraftReminder, valid_reminder(), "estimated_minutes"),
        (WorkLogDraft, {}, "total_minutes"),
        (WorkLogDraft, {}, "hours"),
    ],
    ids=lambda v: v.__name__ if isinstance(v, type) else str(v),
)
def test_unmeasured_time_fields_cannot_be_smuggled_in(model, payload, smuggled):
    """Verify every model rejects extra fields — an unmeasured 'hours' must never ride along."""
    assert model.model_validate(payload) is not None, "baseline payload must be valid"
    with pytest.raises(ValidationError) as exc:
        model.model_validate({**payload, smuggled: 4})
    assert smuggled in str(exc.value)


@pytest.mark.parametrize("field", ["description", "project"])
def test_entry_text_fields_reject_empty_strings(field):
    with pytest.raises(ValidationError) as exc:
        DraftEntry.model_validate(valid_entry(**{field: ""}))
    assert field in str(exc.value)


def test_review_reason_at_limit_accepted():
    entry = DraftEntry.model_validate(valid_entry(review_reason="x" * REVIEW_REASON_MAX_LENGTH))
    assert len(entry.review_reason) == REVIEW_REASON_MAX_LENGTH


def test_review_reason_over_limit_rejected():
    """Verify review_reason has the same runaway-prose backstop as description."""
    with pytest.raises(ValidationError) as exc:
        DraftEntry.model_validate(valid_entry(review_reason="x" * (REVIEW_REASON_MAX_LENGTH + 1)))
    assert "review_reason" in str(exc.value)


def test_reminder_note_at_limit_accepted():
    note = "x" * REMINDER_NOTE_MAX_LENGTH
    assert DraftReminder.model_validate(valid_reminder(note=note)).note == note


def test_reminder_note_over_limit_rejected():
    with pytest.raises(ValidationError) as exc:
        DraftReminder.model_validate(valid_reminder(note="x" * (REMINDER_NOTE_MAX_LENGTH + 1)))
    assert "note" in str(exc.value)
