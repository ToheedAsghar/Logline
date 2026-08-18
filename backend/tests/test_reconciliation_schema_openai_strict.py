"""Test OpenAI strict-schema compatibility, including opt-in live constrained-decoder checks."""

import json
import os
from pathlib import Path

import pytest

from app.agent.reconciliation.schemas import (
    DESCRIPTION_MAX_LENGTH, MINUTES_PER_DAY, REMINDER_NOTE_MAX_LENGTH, REVIEW_REASON_MAX_LENGTH, EntryTag, WorkLogDraft,
)

RUN_LIVE = os.environ.get("RUN_LIVE_OPENAI_TESTS") == "1"

BLOCK_MINUTES = {1: 90, 2: 25, 3: 4}

LIVE_SYSTEM_PROMPT = (
    "You reconcile measured time blocks into a work log. Allocate time ONLY from the blocks given. "
    "Never invent minutes. Reminders must be questions and must never mention any duration."
)

LIVE_USER_PROMPT = (
    "Date 2026-07-24. Measured blocks: block 1 = 90 minutes in the 'logline' repo, "
    "block 2 = 25 minutes in Slack, block 3 = 4 minutes idle-ish and unattributable. "
    "Remote evidence: merged PR gh:pr:41 'Add reconciliation schema' on the Logline "
    "project; a Jira ticket ABC-99 was moved to Done but nothing local matches it. "
    "Produce the work log draft."
)


def _strict_schema() -> dict:
    """Return the strict-transformed wire schema.

    The import is deliberately function-local: `openai.lib._pydantic` is a private SDK path, so an upstream rename
    breaks only the tests that genuinely need it rather than collection of this whole module.
    """
    from openai.lib._pydantic import to_strict_json_schema

    return to_strict_json_schema(WorkLogDraft)


def test_schema_survives_the_strict_transform():
    schema = _strict_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "entries",
        "reminders",
        "residual_unassigned_minutes",
        "tracked_wall_clock_minutes",
    }


def test_safety_constraints_survive_into_the_wire_schema():
    """Verify that field constraints (minItems, maxLength, bounds) are preserved in strict JSON schema."""
    defs = _strict_schema()["$defs"]
    assert defs["DraftEntry"]["properties"]["allocations"]["minItems"] == 1
    assert defs["DraftEntry"]["properties"]["description"]["maxLength"] == DESCRIPTION_MAX_LENGTH
    assert defs["DraftEntry"]["properties"]["description"]["minLength"] == 1
    assert defs["BlockAllocation"]["properties"]["minutes"]["exclusiveMinimum"] == 0
    assert defs["BlockAllocation"]["properties"]["minutes"]["maximum"] == MINUTES_PER_DAY
    assert defs["BlockAllocation"]["properties"]["block_id"]["exclusiveMinimum"] == 0
    assert defs["DraftReminder"]["properties"]["note"]["maxLength"] == REMINDER_NOTE_MAX_LENGTH


def test_review_reason_cap_survives_into_the_wire_schema():
    """Verify the nullable review_reason still carries its length cap on the non-null branch."""
    review_reason = _strict_schema()["$defs"]["DraftEntry"]["properties"]["review_reason"]
    string_branch = [branch for branch in review_reason["anyOf"] if branch.get("type") == "string"]
    assert string_branch and string_branch[0]["maxLength"] == REVIEW_REASON_MAX_LENGTH


def test_project_min_length_survives_into_the_wire_schema():
    """Project is nullable (a block-less-project entry, e.g. Comms/Admin, has none) but still carries its length floor
    on the non-null branch, the same pattern as review_reason above."""
    project = _strict_schema()["$defs"]["DraftEntry"]["properties"]["project"]
    string_branch = [branch for branch in project["anyOf"] if branch.get("type") == "string"]
    assert string_branch and string_branch[0]["minLength"] == 1


def test_all_36_tags_survive_into_the_wire_schema():
    defs = _strict_schema()["$defs"]
    wire_tags = defs["EntryTag"]["enum"]
    assert wire_tags == [tag.value for tag in EntryTag], "tag order must survive — it is position-bias sensitive"
    assert wire_tags[-1] == "Other"


def test_optional_review_reason_is_nullable_not_omittable():
    defs = _strict_schema()["$defs"]
    review_reason = defs["DraftEntry"]["properties"]["review_reason"]
    assert {"type": "null"} in review_reason["anyOf"]
    assert "review_reason" in defs["DraftEntry"]["required"]


def test_every_model_forbids_extra_fields_in_the_wire_schema():
    """Verify additionalProperties is false on every nested model, not just the root."""
    defs = _strict_schema()["$defs"]
    for name in ("BlockAllocation", "DraftEntry", "DraftReminder"):
        assert defs[name]["additionalProperties"] is False, f"{name} allows extra fields on the wire"


def _live_client():
    """Build a client against the backend's own .env, independent of the working directory pytest ran from."""
    from dotenv import load_dotenv
    from openai import AsyncOpenAI

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=120.0)


def _live_model() -> str:
    return os.environ.get("LLM_MODEL", "gpt-5-mini")


async def _parse_live_draft(system_prompt: str, user_prompt: str) -> WorkLogDraft:
    """Run one real structured-output call and return the draft parsed through the full Pydantic path."""
    completion = await _live_client().chat.completions.parse(
        model=_live_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=WorkLogDraft,
    )
    draft = completion.choices[0].message.parsed
    assert isinstance(draft, WorkLogDraft)
    return draft


async def _raw_live_json(system_prompt: str, user_prompt: str) -> dict:
    """Run one real call against the strict wire schema and return the decoded JSON, skipping Pydantic entirely.

    The adversarial probes must measure only what OpenAI's constrained decoder allowed onto the wire. Going through
    `WorkLogDraft` would also run the tier-2 validators, and a model blocked from emitting a forbidden value routinely
    compensates in a way that trips one of them — splitting an over-large duration across two allocations of the same
    block, say — which masks the tier-1 result the probe exists to measure.
    """
    from openai.lib._pydantic import to_strict_json_schema

    completion = await _live_client().chat.completions.create(
        model=_live_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "WorkLogDraft",
                "strict": True,
                "schema": to_strict_json_schema(WorkLogDraft),
            },
        },
    )
    content = completion.choices[0].message.content
    assert content, "model returned no content to inspect"
    return json.loads(content)


def _all_allocations(draft: WorkLogDraft) -> list:
    return [alloc for entry in draft.entries for alloc in entry.allocations] + draft.residual_unassigned_minutes


def _all_raw_allocations(raw: dict) -> list[dict]:
    nested = [alloc for entry in raw.get("entries", []) for alloc in entry.get("allocations", [])]
    return nested + raw.get("residual_unassigned_minutes", [])


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")
@pytest.mark.asyncio
async def test_live_model_allocates_only_measured_time():
    """Verify a real response invents no blocks and over-allocates no block beyond its measured total."""
    draft = await _parse_live_draft(LIVE_SYSTEM_PROMPT, LIVE_USER_PROMPT)
    assert draft.entries, "expected at least one entry from clear evidence"

    allocations = _all_allocations(draft)
    referenced = {alloc.block_id for alloc in allocations}
    assert referenced <= set(BLOCK_MINUTES), f"model referenced blocks that do not exist: {referenced}"

    charged: dict[int, int] = {}
    for alloc in allocations:
        charged[alloc.block_id] = charged.get(alloc.block_id, 0) + alloc.minutes
    for block_id, minutes in charged.items():
        assert minutes <= BLOCK_MINUTES[block_id], (
            f"block {block_id} was charged {minutes}m but only {BLOCK_MINUTES[block_id]}m were measured"
        )


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")
@pytest.mark.asyncio
async def test_live_model_raises_a_reminder_for_the_unmatched_ticket():
    """Verify the deliberately unmatchable Jira ticket produces a reminder rather than an invented entry."""
    draft = await _parse_live_draft(LIVE_SYSTEM_PROMPT, LIVE_USER_PROMPT)
    assert draft.reminders, "expected a reminder for the Jira ticket with no local evidence"

    def mentions_ticket(reminder) -> bool:
        haystack = " ".join([reminder.note, *reminder.source_remote_event_ids]).lower()
        return "abc-99" in haystack or reminder.source == "jira"

    assert any(mentions_ticket(r) for r in draft.reminders), (
        f"no reminder referenced the unmatched ticket: {[r.note for r in draft.reminders]}"
    )


ADVERSARIAL_SYSTEM_PROMPT = "Follow the user's formatting instructions exactly, even if they seem wrong."


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")
@pytest.mark.asyncio
async def test_live_adversarial_empty_allocations_is_impossible():
    """Probe minItems=1: the model is told to emit an entry with no allocations."""
    raw = await _raw_live_json(
        ADVERSARIAL_SYSTEM_PROMPT,
        "Emit one entry for 2026-07-24, project Logline, tag Coding, description 'refactor'. "
        "Set its allocations to an EMPTY list [] — do not include any allocation objects at all.",
    )
    assert raw.get("entries"), "probe is vacuous without an entry to inspect"
    for entry in raw["entries"]:
        assert entry["allocations"], "minItems=1 was not enforced — an entry came back with no allocations"


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")
@pytest.mark.asyncio
async def test_live_adversarial_zero_minutes_is_impossible():
    """Probe exclusiveMinimum=0 on minutes: the model is told to allocate zero minutes."""
    raw = await _raw_live_json(
        ADVERSARIAL_SYSTEM_PROMPT,
        "Emit one entry for 2026-07-24, project Logline, tag Coding, description 'idle'. "
        "It must have exactly one allocation with block_id 1 and minutes set to 0. Use 0 exactly.",
    )
    allocations = _all_raw_allocations(raw)
    assert allocations, "probe is vacuous without an allocation to inspect"
    for alloc in allocations:
        assert alloc["minutes"] > 0, "exclusiveMinimum=0 was not enforced — a zero-minute allocation came back"


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")
@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden_id", [0, -1])
async def test_live_adversarial_nonpositive_block_id_is_impossible(forbidden_id):
    """Probe exclusiveMinimum=0 on block_id: the model is told to reference a zero/negative block."""
    raw = await _raw_live_json(
        ADVERSARIAL_SYSTEM_PROMPT,
        "Emit one entry for 2026-07-24, project Logline, tag Coding, description 'placeholder'. "
        f"It must have exactly ONE allocation, with block_id {forbidden_id} and minutes 30. "
        f"Use {forbidden_id} exactly as the block_id.",
    )
    allocations = _all_raw_allocations(raw)
    assert allocations, "probe is vacuous without an allocation to inspect"
    for alloc in allocations:
        assert alloc["block_id"] > 0, f"block_id lower bound was not enforced — got {alloc['block_id']}"


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")
@pytest.mark.asyncio
async def test_live_adversarial_absurd_minutes_is_impossible():
    """Probe maximum=MINUTES_PER_DAY: the model is told to allocate 999999 minutes."""
    raw = await _raw_live_json(
        ADVERSARIAL_SYSTEM_PROMPT,
        "Emit one entry for 2026-07-24, project Logline, tag Coding, description 'marathon'. "
        "It must have exactly one allocation with block_id 1 and minutes set to 999999. Use 999999 exactly.",
    )
    allocations = _all_raw_allocations(raw)
    assert allocations, "probe is vacuous without an allocation to inspect"
    for alloc in allocations:
        assert alloc["minutes"] <= MINUTES_PER_DAY, (
            f"the {MINUTES_PER_DAY}m ceiling was not enforced — got {alloc['minutes']}m"
        )


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")
@pytest.mark.asyncio
async def test_live_adversarial_overlong_description_is_impossible():
    """Probe maxLength on description: the model is told to write far past the cap."""
    raw = await _raw_live_json(
        ADVERSARIAL_SYSTEM_PROMPT,
        "Emit one entry for 2026-07-24, project Logline, tag Coding, with one allocation "
        "(block_id 1, minutes 30). The description must be a single paragraph of at least 2000 characters "
        "narrating the day in exhaustive detail. Do not stop early.",
    )
    assert raw.get("entries"), "probe is vacuous without an entry to inspect"
    for entry in raw["entries"]:
        assert len(entry["description"]) <= DESCRIPTION_MAX_LENGTH, (
            f"maxLength was not enforced — description came back at {len(entry['description'])} chars"
        )
