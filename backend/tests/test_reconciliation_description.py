"""Test gated per-entry LLM description generation with a scripted provider."""

from datetime import datetime, timedelta, timezone

import pytest

from app.agent.llm.base import LLMProvider, LLMStructuredOutputError, Message
from app.agent.reconciliation.description import describe_entry
from app.agent.reconciliation.entries import form_entries
from app.agent.reconciliation.evidence import build_evidence
from app.agent.reconciliation.schemas import DESCRIPTION_MAX_LENGTH, EntryDescriptionProposal, EntryTag, TagSuggestion
from app.local_activity.aggregation import LocalActivityBlock, TitleCluster
from app.local_activity.classification import SessionCategory
from app.matching.matcher import MatchedGroup, RemoteEventData

UTC = timezone.utc


def make_block(
    project="logline",
    start_hour=9,
    minutes=90,
    category=SessionCategory.coding,
    apps=None,
    title_digest=None,
    deterministic_topic=None,
    urls=None,
):
    start = datetime(2026, 8, 6, start_hour, 0, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project, start_time=start, end_time=start + duration, duration=duration,
        apps=apps if apps is not None else ["vscode"], category=category,
        title_digest=title_digest if title_digest is not None else [],
        deterministic_topic=deterministic_topic,
        urls=[] if urls is None else urls,
    )


def make_event(external_id="logline#41", source="github", occurred_hour=9, summary="Add reconciliation schema"):
    return RemoteEventData(
        external_id=external_id, source=source, remote_project_id="logline",
        occurred_at=datetime(2026, 8, 6, occurred_hour, 30, tzinfo=UTC), event_type="pull_request", summary=summary,
    )


def _one_entry(matched_groups=(), unmatched_blocks=()):
    bundle = build_evidence(list(matched_groups), list(unmatched_blocks), [])
    entries = form_entries(bundle)
    assert len(entries) == 1, "test setup must produce exactly one entry"
    return entries[0], bundle


class QueuedProvider(LLMProvider):
    """Returns each queued response (or raises each queued exception) in order, one per run_structured call.

    Records every call's messages so tests can inspect exactly what the model was shown.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list[Message]] = []

    async def run_structured(self, messages, response_model):
        self.calls.append(messages)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_a_clean_proposal_is_returned_as_is_with_a_single_call(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block()])
        provider = QueuedProvider([EntryDescriptionProposal(description="Logline - coding session in vscode.")])

        description, tag_override = await describe_entry(entry, bundle, provider)

        assert description == "Logline - coding session in vscode."
        assert tag_override is None
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_a_pr_number_present_in_the_entrys_local_title_evidence_is_allowed(self):
        title = "FEAT(auth): Google SSO login by ToheedAsghar · Pull Request #20 · ToheedAsghar/Logline"
        block = make_block(
            project=None,
            category=SessionCategory.code_review,
            title_digest=[TitleCluster(title=title, seconds=60)],
        )
        entry, bundle = _one_entry(unmatched_blocks=[block])
        provider = QueuedProvider([EntryDescriptionProposal(description="Reviewed PR #20 for Google SSO login.")])

        description, tag_override = await describe_entry(entry, bundle, provider)

        assert description == "Reviewed PR #20 for Google SSO login."
        assert tag_override is None
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_a_pr_number_present_only_in_attached_sub_minute_evidence_is_allowed(self):
        topic = ("branch", "feature/review")
        brief = make_block(
            minutes=1 / 6,
            deterministic_topic=topic,
            title_digest=[TitleCluster(title="Reviewed Pull Request #48", seconds=10)],
        )
        real = make_block(minutes=30, deterministic_topic=topic)
        entry, bundle = _one_entry(unmatched_blocks=[brief, real])
        provider = QueuedProvider([EntryDescriptionProposal(description="Reviewed PR #48.")])

        description, _ = await describe_entry(entry, bundle, provider)

        assert description == "Reviewed PR #48."
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "number"),
        [
            ("https://github.com/ToheedAsghar/Logline/pull/58", "58"),
            ("https://gitlab.com/toheedasghar/logline/-/merge_requests/59", "59"),
            ("https://bitbucket.org/toheedasghar/logline/pull-requests/60", "60"),
        ],
    )
    async def test_a_pr_number_present_only_in_a_captured_platform_url_is_allowed(self, url, number):
        """A PR number in rendered GitHub, GitLab, or Bitbucket evidence is cited rather than invented."""
        block = make_block(
            project=None,
            category=SessionCategory.code_review,
            urls=[url],
        )
        entry, bundle = _one_entry(unmatched_blocks=[block])
        provider = QueuedProvider([EntryDescriptionProposal(description=f"Reviewed PR #{number} on Logline.")])

        description, _ = await describe_entry(entry, bundle, provider)

        assert description == f"Reviewed PR #{number} on Logline."
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_a_number_in_an_unrecognized_url_shape_is_rejected(self):
        block = make_block(
            project=None,
            category=SessionCategory.code_review,
            urls=["https://example.com/toheedasghar/logline/changes/61"],
        )
        entry, bundle = _one_entry(unmatched_blocks=[block])
        bad = EntryDescriptionProposal(description="Reviewed PR #61 on Logline.")
        good = EntryDescriptionProposal(description="Reviewed the change on Logline.")
        provider = QueuedProvider([bad, good])

        description, _ = await describe_entry(entry, bundle, provider)

        assert description == "Reviewed the change on Logline."
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_a_pr_number_in_a_url_on_a_different_entrys_block_is_still_rejected(self):
        """Url-sourced numbers widen the gate only for the entry whose own evidence carries the url."""
        block = make_block(
            project=None,
            category=SessionCategory.code_review,
            urls=["https://github.com/ToheedAsghar/Logline/pull/58"],
        )
        entry, bundle = _one_entry(unmatched_blocks=[block])
        bad = EntryDescriptionProposal(description="Reviewed PR #77, which no url vouches for.")
        good = EntryDescriptionProposal(description="Reviewed PR #58 on Logline.")
        provider = QueuedProvider([bad, good])

        description, _ = await describe_entry(entry, bundle, provider)

        assert description == "Reviewed PR #58 on Logline."
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_the_entrys_own_evidence_is_what_gets_sent(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block(minutes=45)])
        provider = QueuedProvider([EntryDescriptionProposal(description="ok")])

        await describe_entry(entry, bundle, provider)

        sent = "\n".join(message.content or "" for message in provider.calls[0])
        assert "block 1 |" in sent
        assert "45 min measured" in sent
        assert "project: logline" in sent

    @pytest.mark.asyncio
    async def test_a_valid_tag_override_is_passed_through(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block(category=SessionCategory.coding)])
        proposal = EntryDescriptionProposal(
            description="Logline - debugging a failing test.",
            tag_suggestion=TagSuggestion(tag=EntryTag.debugging, reason="Evidence shows test debugging"),
        )
        provider = QueuedProvider([proposal])

        _, tag_override = await describe_entry(entry, bundle, provider)

        assert tag_override == EntryTag.debugging


class TestGateRejectsAndRetries:
    @pytest.mark.asyncio
    async def test_an_invented_pr_number_is_rejected_then_the_retry_is_used_if_clean(self):
        entry, bundle = _one_entry(
            matched_groups=[MatchedGroup(block=make_block(), events=[make_event(external_id="logline#41")])]
        )
        bad = EntryDescriptionProposal(description="Worked on PR #99, which is not in evidence.")
        good = EntryDescriptionProposal(description="Worked on PR #41 per the evidence.")
        provider = QueuedProvider([bad, good])

        description, _ = await describe_entry(entry, bundle, provider)

        assert description == "Worked on PR #41 per the evidence."
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_the_retry_message_names_the_violation(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block()])
        bad = EntryDescriptionProposal(description="Invented PR #7 here.")
        good = EntryDescriptionProposal(description="Clean description.")
        provider = QueuedProvider([bad, good])

        await describe_entry(entry, bundle, provider)

        retry_sent = "\n".join(message.content or "" for message in provider.calls[1])
        assert "invented PR #7" in retry_sent

    @pytest.mark.asyncio
    async def test_duration_language_is_rejected(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block()])
        bad = EntryDescriptionProposal(description="Spent about 2 hours on this.")
        good = EntryDescriptionProposal(description="Worked in vscode.")
        provider = QueuedProvider([bad, good])

        description, _ = await describe_entry(entry, bundle, provider)

        assert description == "Worked in vscode."
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_a_no_op_tag_suggestion_is_rejected(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block(category=SessionCategory.coding)])
        bad = EntryDescriptionProposal(
            description="Coding session.",
            tag_suggestion=TagSuggestion(tag=entry.base_tag, reason="No real change"),
        )
        good = EntryDescriptionProposal(description="Coding session, clean.")
        provider = QueuedProvider([bad, good])

        description, tag_override = await describe_entry(entry, bundle, provider)

        assert description == "Coding session, clean."
        assert tag_override is None
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_two_gate_failures_in_a_row_fall_back_to_a_deterministic_description(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block(apps=["vscode", "terminal"])])
        always_bad = EntryDescriptionProposal(description="Spent 3 hours today.")
        provider = QueuedProvider([always_bad, always_bad])

        description, tag_override = await describe_entry(entry, bundle, provider)

        assert tag_override is None
        assert len(provider.calls) == 2
        assert "vscode" in description and "terminal" in description
        assert "3 hours" not in description


class TestProviderFailures:
    @pytest.mark.asyncio
    async def test_a_structured_output_error_is_retried_then_recovers(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block()])
        provider = QueuedProvider(
            [LLMStructuredOutputError("truncated"), EntryDescriptionProposal(description="Recovered fine.")]
        )

        description, _ = await describe_entry(entry, bundle, provider)

        assert description == "Recovered fine."
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_two_structured_output_errors_in_a_row_fall_back_deterministically(self):
        entry, bundle = _one_entry(unmatched_blocks=[make_block()])
        provider = QueuedProvider([LLMStructuredOutputError("truncated"), LLMStructuredOutputError("truncated again")])

        description, tag_override = await describe_entry(entry, bundle, provider)

        assert tag_override is None
        assert description
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_an_unrelated_exception_is_not_swallowed_into_a_fallback(self):
        """A gate violation or a structured-output error both have a defined, safe recovery path.

        A raw, unexpected error (a network failure, a programming bug) is a different class of problem and must
        propagate rather than silently read as "the model produced a bad description".
        """
        entry, bundle = _one_entry(unmatched_blocks=[make_block()])
        provider = QueuedProvider([RuntimeError("connection reset")])

        with pytest.raises(RuntimeError, match="connection reset"):
            await describe_entry(entry, bundle, provider)


class TestFallbackDescription:
    @pytest.mark.asyncio
    async def test_fallback_mentions_matched_event_summaries(self):
        entry, bundle = _one_entry(
            matched_groups=[MatchedGroup(block=make_block(), events=[make_event(summary="Add reconciliation schema")])]
        )
        provider = QueuedProvider([LLMStructuredOutputError("x"), LLMStructuredOutputError("x")])

        description, _ = await describe_entry(entry, bundle, provider)

        assert "Add reconciliation schema" in description

    @pytest.mark.asyncio
    async def test_fallback_never_exceeds_the_description_length_limit(self):
        long_summary = "A very long PR summary that goes on and on. " * 10
        events = [make_event(external_id=f"logline#{i}", summary=long_summary) for i in range(5)]
        entry, bundle = _one_entry(matched_groups=[MatchedGroup(block=make_block(), events=events)])
        provider = QueuedProvider([LLMStructuredOutputError("x"), LLMStructuredOutputError("x")])

        description, _ = await describe_entry(entry, bundle, provider)

        assert len(description) <= DESCRIPTION_MAX_LENGTH
