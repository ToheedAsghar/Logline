"""Tests for Stage 5 evidence assembly (app/agent/reconciliation/evidence.py).

`build_evidence` is a pure transform, so everything here runs offline with fixture data and no LLM. The point of
keeping it pure is that the prompt text can be asserted on directly rather than inferred from a model's reaction
to it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.agent.reconciliation.evidence import (
    NO_BLOCKS_LINE, NO_MATCHED_EVIDENCE_LINE, NO_UNMATCHED_EVENTS_LINE, build_evidence,
)
from app.local_activity.aggregation import LocalActivityBlock
from app.matching.matcher import MatchedGroup, RemoteEventData

UTC = timezone.utc
KARACHI = timezone(timedelta(hours=5))


def make_block(project="logline", start_hour=9, minutes=90, apps=None, day=24):
    start = datetime(2026, 7, day, start_hour, 0, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project,
        start_time=start,
        end_time=start + duration,
        duration=duration,
        apps=["vscode", "terminal"] if apps is None else apps,
    )


def make_event(external_id="gh:pr:41", source="github", project="Toheed/logline", hour=9, minute=47, **kwargs):
    return RemoteEventData(
        external_id=external_id,
        source=source,
        remote_project_id=project,
        occurred_at=datetime(2026, 7, 24, hour, minute, tzinfo=UTC),
        event_type=kwargs.get("event_type", "pull_request"),
        summary=kwargs.get("summary", "Add reconciliation schema"),
    )


class TestBlockIdAssignment:
    def test_matched_blocks_are_numbered_first_then_unmatched_blocks(self):
        matched_a, matched_b = make_block(project="alpha"), make_block(project="beta")
        unmatched = make_block(project="gamma")

        bundle = build_evidence(
            [MatchedGroup(block=matched_a, events=[make_event()]), MatchedGroup(block=matched_b, events=[])],
            [unmatched],
            [],
        )

        assert bundle.blocks_by_id == {1: matched_a, 2: matched_b, 3: unmatched}

    def test_ids_are_one_based_so_every_id_satisfies_the_schemas_gt_zero_bound(self):
        bundle = build_evidence([MatchedGroup(block=make_block(), events=[])], [make_block()], [])

        assert min(bundle.blocks_by_id) == 1
        assert all(block_id > 0 for block_id in bundle.blocks_by_id)

    def test_every_assigned_id_appears_in_the_rendered_message(self):
        bundle = build_evidence(
            [MatchedGroup(block=make_block(project="a"), events=[])],
            [make_block(project="b"), make_block(project="c")],
            [],
        )

        for block_id in bundle.blocks_by_id:
            assert f"block {block_id} |" in bundle.user_content

    def test_input_order_is_preserved_so_the_mapping_is_reproducible(self):
        blocks = [make_block(project=name) for name in ("a", "b", "c")]

        first = build_evidence([], blocks, [])
        second = build_evidence([], blocks, [])

        assert first.user_content == second.user_content
        assert first.blocks_by_id == second.blocks_by_id


class TestRendering:
    def test_block_line_carries_measured_minutes_project_and_apps(self):
        bundle = build_evidence([], [make_block(project="logline", minutes=90, apps=["vscode", "chrome"])], [])

        assert "90 min measured" in bundle.user_content
        assert "project: logline" in bundle.user_content
        assert "apps: vscode, chrome" in bundle.user_content

    def test_block_with_no_apps_says_so_rather_than_rendering_an_empty_list(self):
        bundle = build_evidence([], [make_block(apps=[])], [])

        assert "apps: none recorded" in bundle.user_content

    def test_matched_events_are_listed_under_their_block(self):
        block = make_block()
        event = make_event(external_id="gh:pr:41", summary="Add reconciliation schema")

        content = build_evidence([MatchedGroup(block=block, events=[event])], [], []).user_content

        block_line_index = content.index("block 1 |")
        event_line_index = content.index("id: gh:pr:41")
        assert block_line_index < event_line_index

    def test_matched_group_with_no_events_is_marked_explicitly(self):
        content = build_evidence([MatchedGroup(block=make_block(), events=[])], [], []).user_content

        assert NO_MATCHED_EVIDENCE_LINE in content

    def test_unmatched_blocks_are_included_because_their_measured_time_is_real(self):
        content = build_evidence([], [make_block(project="unwitnessed-work", minutes=45)], []).user_content

        assert "project: unwitnessed-work" in content
        assert "45 min measured" in content

    def test_total_measured_time_sums_every_block(self):
        content = build_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[])],
            [make_block(minutes=25), make_block(minutes=5)],
            [],
        ).user_content

        assert "Total measured time across all blocks: 120 min." in content

    def test_unmatched_events_are_rendered_in_their_own_section(self):
        content = build_evidence([], [], [make_event(external_id="ABC-99", source="jira")]).user_content

        assert "UNMATCHED REMOTE EVENTS" in content
        assert "id: ABC-99" in content

    def test_event_without_a_summary_or_project_renders_without_empty_fields(self):
        event = RemoteEventData(
            external_id="cal:evt:7",
            source="calendar",
            remote_project_id=None,
            occurred_at=datetime(2026, 7, 24, 14, 0, tzinfo=UTC),
            event_type="meeting",
            summary=None,
        )

        content = build_evidence([], [], [event]).user_content

        assert "id: cal:evt:7" in content
        assert "project: None" not in content
        assert "| None" not in content

    def test_empty_inputs_render_explicit_none_markers_not_blank_sections(self):
        content = build_evidence([], [], []).user_content

        assert NO_BLOCKS_LINE in content
        assert NO_UNMATCHED_EVENTS_LINE in content
        assert "Total measured time across all blocks: 0 min." in content


class TestTimezoneHandling:
    def test_datetimes_are_rendered_in_the_requested_timezone(self):
        block = make_block(start_hour=20, minutes=60)

        utc_content = build_evidence([], [block], [], tz=UTC).user_content
        karachi_content = build_evidence([], [block], [], tz=KARACHI).user_content

        assert "2026-07-24 20:00-21:00" in utc_content
        assert "2026-07-25 01:00-02:00" in karachi_content

    def test_naive_block_datetime_is_rejected_rather_than_assumed_to_be_local(self):
        naive = LocalActivityBlock(
            project="logline",
            start_time=datetime(2026, 7, 24, 9, 0),
            end_time=datetime(2026, 7, 24, 10, 0),
            duration=timedelta(minutes=60),
            apps=["vscode"],
        )

        with pytest.raises(ValueError, match="timezone-aware"):
            build_evidence([], [naive], [])

    def test_naive_event_datetime_is_rejected_and_names_the_event(self):
        naive_event = RemoteEventData(
            external_id="gh:pr:7",
            source="github",
            remote_project_id="Toheed/logline",
            occurred_at=datetime(2026, 7, 24, 9, 47),
            event_type="pull_request",
            summary="Naive",
        )

        with pytest.raises(ValueError, match="gh:pr:7"):
            build_evidence([], [], [naive_event])


class TestPrebuiltRemindersNeverReachThePrompt:
    def test_build_evidence_does_not_accept_reminders_at_all(self):
        """The architecture keeps pre-built reminders out of the prompt; the signature is what enforces it."""
        import inspect

        parameters = inspect.signature(build_evidence).parameters

        assert "reminders" not in parameters
        assert list(parameters) == ["matched_groups", "unmatched_blocks", "unmatched_events", "tz"]

    def test_prompt_tells_the_model_unmatched_events_are_already_covered(self):
        content = build_evidence([], [], [make_event()]).user_content

        assert "already exist" in content
        assert "do not re-raise" in content
