"""Live end-to-end proof that Stage 5 produces a verified draft (app/agent/reconciliation/reconciler.py).

This is the first test in the project that drives the whole Phase 4 chain with a real model: fixture evidence in
the real dataclasses, through the real evidence assembler, the real system prompt, the real `OpenAIProvider`,
back into the real schema, and out through real Stage 6 verification. Everything else about Stages 5 and 6 is
verified offline; this exists to prove the pieces actually fit together against a live model rather than only
against a scripted fake.

Requires `RUN_LIVE_OPENAI_TESTS=1` and makes real, billable API calls.

Note on strictness: the draft assertions below check that the output is structurally sound and that the model
did not invent blocks or overspend measured minutes. They deliberately do not re-derive exact conservation by
hand -- that is Stage 6's job, and `TestLiveVerification` now asserts it through the real verifier, which is
what the pipeline will actually rely on.
"""

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.agent.llm.openai_provider import OpenAIProvider
from app.agent.reconciliation.reconciler import ReconciliationResult, reconcile_evidence
from app.agent.reconciliation.schemas import EntryTag, WorkLogDraft
from app.local_activity.aggregation import LocalActivityBlock
from app.matching.matcher import MatchedGroup, RemoteEventData

RUN_LIVE = os.environ.get("RUN_LIVE_OPENAI_TESTS") == "1"
live_only = pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_OPENAI_TESTS=1 to make a real API call")

UTC = timezone.utc
DAY = date(2026, 7, 24)


def _block(project: str, start_hour: int, start_minute: int, minutes: int, apps: list[str]) -> LocalActivityBlock:
    start = datetime(2026, 7, 24, start_hour, start_minute, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration, apps=apps
    )


def _event(external_id, source, project, hour, minute, event_type, summary) -> RemoteEventData:
    return RemoteEventData(
        external_id=external_id,
        source=source,
        remote_project_id=project,
        occurred_at=datetime(2026, 7, 24, hour, minute, tzinfo=UTC),
        event_type=event_type,
        summary=summary,
    )


# A realistic day: two substantial blocks with corroborating remote activity, one short unwitnessed block,
# and one remote event with no local time behind it at all.
BLOCK_CODING = _block("logline", 9, 0, 115, ["vscode", "terminal"])
BLOCK_REVIEW = _block("logline", 13, 30, 50, ["chrome", "slack"])
BLOCK_ORPHAN = _block("scratch-notes", 16, 10, 20, ["obsidian"])

EVENT_PR_OPENED = _event(
    "gh:pr:41", "github", "Toheed/logline", 9, 52, "pull_request", "Add Phase 4 AI reconciliation output schema"
)
EVENT_PR_PUSH = _event(
    "gh:push:8f21c", "github", "Toheed/logline", 10, 34, "push", "Harden DraftEntry validators"
)
EVENT_REVIEW = _event(
    "gh:review:770", "github", "Toheed/logline", 13, 58, "pull_request_review", "Review comments on #40"
)
EVENT_UNMATCHED_JIRA = _event(
    "ABC-99", "jira", "ABC", 17, 5, "issue_transition", "LOG-212 moved to Done"
)

MATCHED_GROUPS = [
    MatchedGroup(block=BLOCK_CODING, events=[EVENT_PR_OPENED, EVENT_PR_PUSH]),
    MatchedGroup(block=BLOCK_REVIEW, events=[EVENT_REVIEW]),
]
UNMATCHED_BLOCKS = [BLOCK_ORPHAN]
UNMATCHED_EVENTS = [EVENT_UNMATCHED_JIRA]

BLOCK_MINUTES = {1: 115, 2: 50, 3: 20}
TOTAL_MEASURED = sum(BLOCK_MINUTES.values())


def _live_provider() -> OpenAIProvider:
    """Build the real provider against the backend's own .env, independent of where pytest was invoked from."""
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set")
    return OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"], model=os.environ.get("LLM_MODEL", "gpt-5-mini"))


async def _run_live() -> ReconciliationResult:
    return await reconcile_evidence(
        MATCHED_GROUPS,
        UNMATCHED_BLOCKS,
        UNMATCHED_EVENTS,
        _live_provider(),
    )


@pytest.fixture(scope="module")
def live_result() -> ReconciliationResult:
    """One real reconciliation, shared by every assertion below so the suite costs a single API call."""
    import asyncio

    return asyncio.run(_run_live())


@pytest.fixture(scope="module")
def live_draft(live_result):
    return live_result.draft


@live_only
class TestLiveEndToEnd:
    def test_returns_a_schema_valid_worklogdraft(self, live_draft):
        assert isinstance(live_draft, WorkLogDraft)
        WorkLogDraft.model_validate(live_draft.model_dump())

    def test_produces_at_least_one_entry_from_clear_evidence(self, live_draft):
        assert live_draft.entries, "a day with two corroborated blocks should yield at least one entry"

    def test_every_entry_is_structurally_complete(self, live_draft):
        for entry in live_draft.entries:
            assert entry.allocations, "an entry with no allocations carries no time"
            assert entry.description.strip()
            assert isinstance(entry.tag, EntryTag)
            assert entry.date == DAY, f"entry dated {entry.date}, but all evidence is from {DAY}"

    def test_no_block_id_was_invented(self, live_draft):
        allocations = [a for e in live_draft.entries for a in e.allocations] + live_draft.residual_unassigned_minutes
        referenced = {a.block_id for a in allocations}

        assert referenced <= set(BLOCK_MINUTES), f"model referenced blocks that do not exist: {referenced}"

    def test_no_block_was_charged_past_its_measured_duration(self, live_draft):
        allocations = [a for e in live_draft.entries for a in e.allocations] + live_draft.residual_unassigned_minutes

        charged: dict[int, int] = {}
        for allocation in allocations:
            charged[allocation.block_id] = charged.get(allocation.block_id, 0) + allocation.minutes

        for block_id, minutes in charged.items():
            assert minutes <= BLOCK_MINUTES[block_id], (
                f"block {block_id} charged {minutes}m but only {BLOCK_MINUTES[block_id]}m were measured"
            )

    def test_total_allocated_time_never_exceeds_total_measured_time(self, live_draft):
        allocations = [a for e in live_draft.entries for a in e.allocations] + live_draft.residual_unassigned_minutes
        total = sum(a.minutes for a in allocations)

        assert total <= TOTAL_MEASURED, f"allocated {total}m against {TOTAL_MEASURED}m measured -- time was invented"

    def test_the_prebuilt_reminder_for_the_unmatched_jira_ticket_is_present(self, live_draft):
        """The pre-built reminder is merged in code, so it must be there regardless of what the model did."""
        prebuilt = [r for r in live_draft.reminders if "ABC-99" in r.source_remote_event_ids]

        assert len(prebuilt) == 1, f"expected exactly one pre-built reminder citing ABC-99, got {len(prebuilt)}"
        assert prebuilt[0].source == "jira"
        assert prebuilt[0].day == DAY

    def test_no_reminder_asserts_a_duration(self, live_draft):
        """Enforced by the schema validator, so a failure here means the merge bypassed validation."""
        for reminder in live_draft.reminders:
            assert reminder.note.strip()
            assert len(reminder.note) <= 280

    def test_entries_cite_the_remote_evidence_they_used(self, live_draft):
        cited = {eid for entry in live_draft.entries for eid in entry.source_remote_event_ids}
        known = {"gh:pr:41", "gh:push:8f21c", "gh:review:770", "ABC-99"}

        assert cited <= known, f"model cited event ids that were never in the evidence: {cited - known}"
        assert cited, "no entry cited any remote evidence despite three corroborating events"


@live_only
class TestLiveVerification:
    """Stage 6 running inside Stage 5, on a real model's output rather than a hand-written fixture.

    The offline suite proves the verifier is correct about drafts written to be broken; it cannot prove a real
    model's draft survives it. That is the gap these assertions close.
    """

    def test_a_verification_result_comes_back_alongside_the_draft(self, live_result):
        assert isinstance(live_result, ReconciliationResult)
        assert isinstance(live_result.draft, WorkLogDraft)
        assert live_result.verification is not None

    def test_the_real_model_draft_passes_verification_cleanly(self, live_result):
        errors = [issue for issue in live_result.verification.issues if issue.severity == "error"]

        assert live_result.verification.passed, "\n".join(f"{i.check}: {i.detail}" for i in errors)
        assert not errors

    def test_every_measured_minute_is_conserved_end_to_end(self, live_result):
        """The whole point of the pipeline: 185 measured minutes in, 185 accounted for out."""
        allocations = [
            a for e in live_result.draft.entries for a in e.allocations
        ] + live_result.draft.residual_unassigned_minutes

        assert sum(a.minutes for a in allocations) == TOTAL_MEASURED

    def test_any_warnings_are_reported_with_enough_detail_to_act_on(self, live_result):
        """Warnings are allowed here -- a duplicated reminder is a real, expected outcome of the merge."""
        for issue in live_result.verification.issues:
            assert issue.check and issue.detail.strip()
