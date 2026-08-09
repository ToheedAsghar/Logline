"""Test reconciliation evidence assembly and entry-specific rendering."""

from datetime import datetime, timedelta, timezone

import pytest

from app.agent.reconciliation.evidence import (
    NO_MATCHED_EVIDENCE_LINE, block_minutes, build_evidence, render_entry_evidence,
)
from app.local_activity.aggregation import LocalActivityBlock, TitleCluster
from app.local_activity.classification import SessionCategory
from app.matching.matcher import MatchedGroup, RemoteEventData

UTC = timezone.utc
KARACHI = timezone(timedelta(hours=5))


def make_block(
    project="logline",
    start_hour=9,
    minutes=90,
    apps=None,
    day=24,
    category=SessionCategory.coding,
    title_digest=None,
    deterministic_topic=None,
):
    start = datetime(2026, 7, day, start_hour, 0, tzinfo=UTC)
    duration = timedelta(minutes=minutes)
    return LocalActivityBlock(
        project=project,
        start_time=start,
        end_time=start + duration,
        duration=duration,
        apps=["vscode", "terminal"] if apps is None else apps,
        category=category,
        title_digest=[] if title_digest is None else title_digest,
        deterministic_topic=deterministic_topic,
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


def render_all(bundle, tz=UTC):
    """Render every chargeable block in one text, the way a single entry's evidence is rendered."""
    return render_entry_evidence(list(bundle.blocks_by_id), bundle, tz=tz)


def total_measured_minutes(bundle):
    return sum(block_minutes(block) for block in bundle.blocks_by_id.values())


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

    def test_every_assigned_id_appears_in_the_rendered_entry_evidence(self):
        bundle = build_evidence(
            [MatchedGroup(block=make_block(project="a"), events=[])],
            [make_block(project="b"), make_block(project="c")],
            [],
        )

        content = render_all(bundle)
        for block_id in bundle.blocks_by_id:
            assert f"block {block_id} |" in content

    def test_input_order_is_preserved_so_the_mapping_is_reproducible(self):
        blocks = [make_block(project=name) for name in ("a", "b", "c")]

        first = build_evidence([], blocks, [])
        second = build_evidence([], blocks, [])

        assert first.blocks_by_id == second.blocks_by_id
        assert render_all(first) == render_all(second)


class TestRendering:
    def test_block_line_carries_measured_minutes_project_and_apps(self):
        bundle = build_evidence([], [make_block(project="logline", minutes=90, apps=["vscode", "chrome"])], [])

        content = render_all(bundle)
        assert "90 min measured" in content
        assert "project: logline" in content
        assert "apps: vscode, chrome" in content

    def test_block_with_no_apps_says_so_rather_than_rendering_an_empty_list(self):
        bundle = build_evidence([], [make_block(apps=[])], [])

        assert "apps: none recorded" in render_all(bundle)

    def test_matched_events_are_listed_under_their_block(self):
        block = make_block()
        event = make_event(external_id="gh:pr:41", summary="Add reconciliation schema")

        content = render_all(build_evidence([MatchedGroup(block=block, events=[event])], [], []))

        block_line_index = content.index("block 1 |")
        event_line_index = content.index("id: gh:pr:41")
        assert block_line_index < event_line_index

    def test_matched_group_with_no_events_is_marked_explicitly(self):
        content = render_all(build_evidence([MatchedGroup(block=make_block(), events=[])], [], []))

        assert NO_MATCHED_EVIDENCE_LINE in content

    def test_unmatched_blocks_are_included_because_their_measured_time_is_real(self):
        content = render_all(build_evidence([], [make_block(project="unwitnessed-work", minutes=45)], []))

        assert "project: unwitnessed-work" in content
        assert "45 min measured" in content

    def test_total_measured_time_sums_every_block(self):
        bundle = build_evidence(
            [MatchedGroup(block=make_block(minutes=90), events=[])],
            [make_block(minutes=25), make_block(minutes=5)],
            [],
        )

        assert total_measured_minutes(bundle) == 120

    def test_matched_event_without_a_summary_or_project_renders_without_empty_fields(self):
        event = RemoteEventData(
            external_id="cal:evt:7",
            source="calendar",
            remote_project_id=None,
            occurred_at=datetime(2026, 7, 24, 14, 0, tzinfo=UTC),
            event_type="meeting",
            summary=None,
        )

        content = render_all(build_evidence([MatchedGroup(block=make_block(), events=[event])], [], []))

        assert "id: cal:evt:7" in content
        assert "project: None" not in content
        assert "| None" not in content

    def test_empty_inputs_produce_an_empty_bundle_rather_than_failing(self):
        bundle = build_evidence([], [], [])

        assert bundle.blocks_by_id == {}
        assert bundle.remote_event_ids == frozenset()
        assert total_measured_minutes(bundle) == 0
        assert render_all(bundle) == ""


class TestUnmatchedEventsAreTrackedButNeverRendered:
    """Unmatched events exist only as ids on the bundle.

    Nothing renders them, so no model can see one and write an entry claiming credit for work that has no measured time
    behind it.
    """

    def test_unmatched_event_ids_are_recorded_on_the_bundle(self):
        bundle = build_evidence([], [], [make_event(external_id="ABC-99", source="jira")])

        assert "ABC-99" in bundle.remote_event_ids

    def test_unmatched_events_never_appear_in_any_rendered_evidence(self):
        bundle = build_evidence([], [make_block()], [make_event(external_id="ABC-99", source="jira")])

        assert "ABC-99" not in render_all(bundle)


class TestZeroMinuteBlockExclusion:
    """A block that rounds to 0 measured minutes can never be legally cited -- BlockAllocation.minutes requires a value
    greater than zero -- so it must never be assigned an id or rendered at all."""

    def test_unmatched_zero_minute_block_gets_no_id_and_is_not_rendered(self):
        zero = make_block(project="flicker", minutes=0)
        real = make_block(project="logline", minutes=30)

        bundle = build_evidence([], [zero, real], [])

        assert list(bundle.blocks_by_id.values()) == [real]
        assert "flicker" not in render_all(bundle)

    def test_matched_zero_minute_block_folds_its_events_into_unmatched_instead_of_dropping_them(self):
        zero = make_block(project="flicker", minutes=0)
        event = make_event(external_id="gh:pr:99", summary="Quick fix")

        bundle = build_evidence([MatchedGroup(block=zero, events=[event])], [], [])

        assert bundle.blocks_by_id == {}
        assert "gh:pr:99" in bundle.remote_event_ids

    def test_zero_minute_blocks_do_not_affect_total_measured_time(self):
        zero = make_block(project="flicker", minutes=0)
        real = make_block(project="logline", minutes=45)

        assert total_measured_minutes(build_evidence([], [zero, real], [])) == 45

    def test_all_blocks_zero_minutes_leaves_no_chargeable_block(self):
        bundle = build_evidence([], [make_block(project="flicker", minutes=0)], [])

        assert bundle.blocks_by_id == {}


class TestPositiveSubMinuteEvidence:
    def test_compatible_zero_rounded_block_attaches_to_the_nearest_surviving_block(self):
        brief = make_block(
            project="logline",
            start_hour=9,
            minutes=1 / 6,
            title_digest=[TitleCluster(title="PR #45", seconds=10)],
            deterministic_topic=("branch", "feature/evidence"),
        )
        real = make_block(
            project="logline",
            start_hour=9,
            minutes=30,
            deterministic_topic=("branch", "feature/evidence"),
        )

        bundle = build_evidence([], [brief, real], [])

        content = render_all(bundle)
        assert list(bundle.blocks_by_id.values()) == [real]
        assert bundle.supplemental_by_block_id == {1: [brief]}
        assert "supplemental local evidence | <1 min observed" in content
        assert 'title | <1 min observed | "PR #45"' in content
        assert total_measured_minutes(bundle) == 30

    def test_incompatible_zero_rounded_block_is_retained_as_unallocated_supplemental_evidence(self):
        brief = make_block(
            project="other",
            start_hour=9,
            minutes=1 / 6,
            title_digest=[TitleCluster(title="AccountSettingsModal.tsx", seconds=10)],
            deterministic_topic=("project_name", "other"),
        )
        real = make_block(project="logline", start_hour=9, minutes=30)

        bundle = build_evidence([], [brief, real], [])

        assert bundle.supplemental_by_block_id == {}
        assert bundle.unallocated_supplemental == [brief]
        assert "AccountSettingsModal.tsx" not in render_all(bundle)


class TestTimezoneHandling:
    def test_datetimes_are_rendered_in_the_requested_timezone(self):
        bundle = build_evidence([], [make_block(start_hour=20, minutes=60)], [])

        assert "2026-07-24 20:00-21:00" in render_all(bundle, tz=UTC)
        assert "2026-07-25 01:00-02:00" in render_all(bundle, tz=KARACHI)

    def test_naive_block_datetime_is_rejected_rather_than_assumed_to_be_local(self):
        naive = LocalActivityBlock(
            project="logline",
            start_time=datetime(2026, 7, 24, 9, 0),
            end_time=datetime(2026, 7, 24, 10, 0),
            duration=timedelta(minutes=60),
            apps=["vscode"],
            category=SessionCategory.coding,
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

    def test_naive_matched_meeting_block_is_rejected_even_though_it_is_never_rendered(self):
        """A Meeting entry's description is copied from its calendar event, so its block never reaches a rendered
        evidence text -- `build_evidence` is the only place a naive one can still be caught."""
        naive = LocalActivityBlock(
            project=None,
            start_time=datetime(2026, 7, 24, 11, 0),
            end_time=datetime(2026, 7, 24, 11, 30),
            duration=timedelta(minutes=30),
            apps=["chrome"],
            category=SessionCategory.meeting,
        )

        with pytest.raises(ValueError, match="timezone-aware"):
            build_evidence([MatchedGroup(block=naive, events=[make_event()])], [], [])


class TestPrebuiltRemindersNeverReachThePrompt:
    def test_build_evidence_does_not_accept_reminders_at_all(self):
        """The architecture keeps pre-built reminders out of the prompt; the signature is what enforces it."""
        import inspect

        parameters = inspect.signature(build_evidence).parameters

        assert "reminders" not in parameters
        assert list(parameters) == ["matched_groups", "unmatched_blocks", "unmatched_events"]
