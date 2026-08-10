"""Assemble structured reconciliation evidence from activity blocks and remote events."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from app.agent.reconciliation.constants import (
    EVENT_INDENT, FRAGMENT_CLUSTER_MAX_SPAN_MINUTES, FRAGMENT_CLUSTER_MIN_BLOCKS, NO_MATCHED_EVIDENCE_LINE,
)
from app.local_activity.aggregation import LocalActivityBlock, TitleCluster
from app.local_activity.classification import SessionCategory
from app.local_activity.constants import CONTEXT_FIELDS, MERGE_GAP_THRESHOLD_MINUTES
from app.matching.matcher import MatchedGroup, RemoteEventData

TITLE_LINE_BREAKS_RE = re.compile(r"[\r\n]+")

CONTEXT_LINE_LABELS: tuple[tuple[str, str], ...] = (
    ("branches", "branches"),
    ("project_names", "project names"),
    ("active_files", "active files"),
    ("tools", "tools"),
    ("urls", "urls"),
    ("cwds", "working dirs"),
    ("browsers", "browsers"),
    ("end_reasons", "end reasons"),
    ("bundle_ids", "bundle ids"),
)


@dataclass(frozen=True)
class EvidenceBundle:
    """Contain chargeable blocks, matched events, overlaps, and supplemental local evidence.

    `unallocated_supplemental` is excluded from LLM-facing context because no entry can cite it.
    """

    blocks_by_id: dict[int, LocalActivityBlock]
    remote_event_ids: frozenset[str]
    unmatched_events: list[RemoteEventData]
    block_events: dict[int, list[RemoteEventData]]
    overlaps: dict[int, list[int]]
    supplemental_by_block_id: dict[int, list[LocalActivityBlock]]
    unallocated_supplemental: list[LocalActivityBlock]


def _require_aware(moment: datetime, label: str) -> None:
    """Reject naive datetimes, which would be silently read as this process's local time when converted."""
    if moment.tzinfo is None:
        raise ValueError(
            f"build_evidence requires timezone-aware datetimes, but {label} is naive. Attach a tzinfo "
            f"(e.g. timezone.utc) upstream -- converting a naive datetime downstream would silently assume "
            f"this process's local timezone and could place the work on the wrong day."
        )


def block_minutes(block: LocalActivityBlock) -> int:
    """Return a block's measured duration in whole minutes."""
    return round(block.duration.total_seconds() / 60)


def _format_block_line(block_id: int, block: LocalActivityBlock, tz: tzinfo, overlapping_ids: list[int]) -> str:
    _require_aware(block.start_time, f"block {block_id} start_time")
    _require_aware(block.end_time, f"block {block_id} end_time")

    start = block.start_time.astimezone(tz)
    end = block.end_time.astimezone(tz)
    apps = ", ".join(block.apps) if block.apps else "none recorded"
    line = (
        f"block {block_id} | {start.date().isoformat()} {start:%H:%M}-{end:%H:%M} | "
        f"{block_minutes(block)} min measured | category: {block.category.value} | "
        f"project: {block.project} | apps: {apps}"
    )
    if overlapping_ids:
        ids = ", ".join(str(other_id) for other_id in overlapping_ids)
        line += f" | overlaps block(s): {ids}"
    if block.deterministic_topic is not None:
        line += f" | topic: {block.deterministic_topic[0]} {block.deterministic_topic[1]}"
    return line


def _sanitize_title(title: str) -> str:
    """Collapse line breaks and replace double quotes in a rendered title."""
    collapsed = TITLE_LINE_BREAKS_RE.sub(" ", title)
    return collapsed.replace('"', "'")


def _format_title_line(cluster: TitleCluster) -> str:
    duration = "<1 min observed" if cluster.seconds < 60 else f"{round(cluster.seconds / 60)} min"
    return f'{EVENT_INDENT}title | {duration} | "{_sanitize_title(cluster.title)}"'


def _format_context_line(block: LocalActivityBlock) -> str | None:
    """Render a block's captured context signals, or None when it has none."""
    rendered = [
        f"{label}: {', '.join(_sanitize_title(value) for value in values)}"
        for attribute, label in CONTEXT_LINE_LABELS
        if (values := getattr(block, attribute))
    ]
    if not rendered:
        return None
    return EVENT_INDENT + "context | " + " | ".join(rendered)


def compute_tracked_wall_clock_minutes(blocks: Iterable[LocalActivityBlock]) -> int:
    """Return the union of the given block spans in whole minutes, counting concurrent time once.

    Summing each block instead would double-count genuinely overlapping work, such as a meeting running alongside
    a non-meeting block, so the spans are merged before measuring. Pass measured aggregation blocks, whose span
    equals their duration -- a bundle's merged cluster blocks span the gaps between their fragments and would
    inflate the total.
    """
    spans = sorted((block.start_time, block.end_time) for block in blocks)

    tracked = timedelta()
    merged_start: datetime | None = None
    merged_end: datetime | None = None
    for start, end in spans:
        if merged_end is None or start > merged_end:
            if merged_end is not None:
                tracked += merged_end - merged_start
            merged_start, merged_end = start, end
            continue
        merged_end = max(merged_end, end)
    if merged_end is not None:
        tracked += merged_end - merged_start

    return round(tracked.total_seconds() / 60)


def compute_overlaps(blocks_by_id: dict[int, LocalActivityBlock]) -> dict[int, list[int]]:
    """Return pairwise wall-clock overlaps for every block."""
    overlaps: dict[int, list[int]] = {block_id: [] for block_id in blocks_by_id}
    ids = sorted(blocks_by_id)
    for index, id_a in enumerate(ids):
        block_a = blocks_by_id[id_a]
        for id_b in ids[index + 1 :]:
            block_b = blocks_by_id[id_b]
            if block_a.start_time < block_b.end_time and block_b.start_time < block_a.end_time:
                overlaps[id_a].append(id_b)
                overlaps[id_b].append(id_a)
    return overlaps


@dataclass(frozen=True)
class FragmentCluster:
    """Represent one contiguous run of project-less activity fragments."""

    block_ids: list[int]
    span_minutes: int


def compute_fragment_clusters(blocks_by_id: dict[int, LocalActivityBlock]) -> list[FragmentCluster]:
    """Group chronologically adjacent, project-less, non-Meeting blocks into fragment clusters.

    Eligible blocks have no project and are not Meetings. Process blocks by `start_time`; a run closes at
    `FRAGMENT_CLUSTER_MAX_SPAN_MINUTES`, a gap of `MERGE_GAP_THRESHOLD_MINUTES` or more, or a conflicting topic.
    Emit runs with at least `FRAGMENT_CLUSTER_MIN_BLOCKS` members.

    Pure detection: does not mutate `blocks_by_id`; `build_evidence` performs the merge.
    """
    chronological_ids = sorted(blocks_by_id, key=lambda block_id: blocks_by_id[block_id].start_time)

    clusters: list[FragmentCluster] = []
    current: list[int] = []
    current_topics: set[tuple[str, str]] = set()

    def _close_current() -> None:
        if len(current) >= FRAGMENT_CLUSTER_MIN_BLOCKS:
            span = round(
                (blocks_by_id[current[-1]].end_time - blocks_by_id[current[0]].start_time).total_seconds() / 60
            )
            clusters.append(FragmentCluster(block_ids=list(current), span_minutes=span))
        current.clear()
        current_topics.clear()

    for block_id in chronological_ids:
        block = blocks_by_id[block_id]
        eligible = block.project is None and block.category != SessionCategory.meeting
        if not eligible:
            _close_current()
            continue

        if current:
            prev = blocks_by_id[current[-1]]
            gap_minutes = (block.start_time - prev.end_time).total_seconds() / 60
            span_if_added = (block.end_time - blocks_by_id[current[0]].start_time).total_seconds() / 60
            topic_conflicts = (
                block.deterministic_topic is not None
                and current_topics
                and block.deterministic_topic not in current_topics
            )
            if (
                gap_minutes >= MERGE_GAP_THRESHOLD_MINUTES
                or span_if_added > FRAGMENT_CLUSTER_MAX_SPAN_MINUTES
                or topic_conflicts
            ):
                _close_current()

        current.append(block_id)
        if block.deterministic_topic is not None:
            current_topics.add(block.deterministic_topic)

    _close_current()
    return clusters


def _merge_cluster_block(blocks_by_id: dict[int, LocalActivityBlock], cluster: FragmentCluster) -> LocalActivityBlock:
    """Merge a fragment cluster into one project-less block.

    Duration is the sum of member durations; category is the longest member category, with first-member ties.
    """
    members = [blocks_by_id[block_id] for block_id in cluster.block_ids]

    duration = sum((member.duration for member in members), timedelta())

    duration_by_category: dict[SessionCategory, timedelta] = {}
    for member in members:
        duration_by_category[member.category] = duration_by_category.get(member.category, timedelta()) + member.duration
    max_duration = max(duration_by_category.values())
    category = next(cat for cat, dur in duration_by_category.items() if dur == max_duration)

    apps: list[str] = []
    for member in members:
        for app in member.apps:
            if app not in apps:
                apps.append(app)

    deterministic_topic = next(
        (member.deterministic_topic for member in members if member.deterministic_topic is not None), None
    )
    if (
        deterministic_topic is not None
        and deterministic_topic[0] == "pr"
        and category != SessionCategory.code_review
    ):
        deterministic_topic = None

    def _union(attribute: str) -> list[str]:
        values: list[str] = []
        for member in members:
            for value in getattr(member, attribute):
                if value not in values:
                    values.append(value)
        return values

    seconds_by_title: dict[str, float] = {}
    for member in members:
        for title_cluster in member.title_digest:
            seconds_by_title[title_cluster.title] = (
                seconds_by_title.get(title_cluster.title, 0) + title_cluster.seconds
            )
    title_digest = sorted(
        (TitleCluster(title=title, seconds=seconds) for title, seconds in seconds_by_title.items()),
        key=lambda title_cluster: title_cluster.seconds,
        reverse=True,
    )

    return LocalActivityBlock(
        project=None,
        start_time=members[0].start_time,
        end_time=members[-1].end_time,
        duration=duration,
        apps=apps,
        category=category,
        title_digest=title_digest,
        deterministic_topic=deterministic_topic,
        **{block_attribute: _union(block_attribute) for _, block_attribute in CONTEXT_FIELDS},
    )


def _format_event_line(event: RemoteEventData, tz: tzinfo, indent: str) -> str:
    _require_aware(event.occurred_at, f"remote event {event.external_id!r} occurred_at")

    occurred = event.occurred_at.astimezone(tz)
    parts = [
        f"{event.source}/{event.event_type}",
        f"id: {event.external_id}",
        f"{occurred.date().isoformat()} {occurred:%H:%M}",
    ]
    if event.remote_project_id:
        parts.append(f"project: {event.remote_project_id}")
    if event.summary:
        parts.append(event.summary)
    return indent + " | ".join(parts)


def _block_gap(first: LocalActivityBlock, second: LocalActivityBlock) -> timedelta:
    if first.end_time <= second.start_time:
        return second.start_time - first.end_time
    if second.end_time <= first.start_time:
        return first.start_time - second.end_time
    return timedelta()


def _supplemental_key(block: LocalActivityBlock) -> tuple:
    return (block.start_time.date(), block.project, block.category, block.deterministic_topic)


def _format_supplemental_block(block: LocalActivityBlock, tz: tzinfo) -> list[str]:
    _require_aware(block.start_time, "supplemental block start_time")
    _require_aware(block.end_time, "supplemental block end_time")
    start = block.start_time.astimezone(tz)
    end = block.end_time.astimezone(tz)
    line = (
        f"{EVENT_INDENT}supplemental local evidence | <1 min observed | "
        f"{start.date().isoformat()} {start:%H:%M:%S}-{end:%H:%M:%S} | "
        f"category: {block.category.value} | project: {block.project}"
    )
    if block.deterministic_topic is not None:
        line += f" | topic: {block.deterministic_topic[0]} {block.deterministic_topic[1]}"
    lines = [line]
    lines.extend(_format_title_line(cluster) for cluster in block.title_digest)
    context_line = _format_context_line(block)
    if context_line is not None:
        lines.append(context_line)
    return lines


def build_evidence(
    matched_groups: list[MatchedGroup],
    unmatched_blocks: list[LocalActivityBlock],
    unmatched_events: list[RemoteEventData],
) -> EvidenceBundle:
    """Assemble matched and unmatched activity into a structured evidence bundle.

    Assign 1-based IDs after fragment merging. Zero-rounded blocks become nearby supplemental evidence when possible;
    their matched events remain unmatched so reminder generation can handle them. Reject naive datetimes.
    """
    for index, block in enumerate([group.block for group in matched_groups] + unmatched_blocks):
        _require_aware(block.start_time, f"block at position {index} start_time")
        _require_aware(block.end_time, f"block at position {index} end_time")
    for event in [event for group in matched_groups for event in group.events] + unmatched_events:
        _require_aware(event.occurred_at, f"remote event {event.external_id!r} occurred_at")

    provisional_blocks_by_id: dict[int, LocalActivityBlock] = {}
    provisional_events_by_id: dict[int, list[RemoteEventData]] = {}
    provisional_order: list[int] = []
    orphaned_events: list[RemoteEventData] = []

    for group in matched_groups:
        provisional_id = len(provisional_blocks_by_id) + 1
        provisional_blocks_by_id[provisional_id] = group.block
        provisional_events_by_id[provisional_id] = group.events
        provisional_order.append(provisional_id)

    for block in unmatched_blocks:
        provisional_id = len(provisional_blocks_by_id) + 1
        provisional_blocks_by_id[provisional_id] = block
        provisional_events_by_id[provisional_id] = []
        provisional_order.append(provisional_id)

    order_position = {provisional_id: index for index, provisional_id in enumerate(provisional_order)}
    clusters = compute_fragment_clusters(provisional_blocks_by_id)
    cluster_by_anchor = {
        min(cluster.block_ids, key=lambda provisional_id: order_position[provisional_id]): cluster
        for cluster in clusters
    }
    absorbed_ids = {
        provisional_id
        for cluster in clusters
        for provisional_id in cluster.block_ids
        if provisional_id not in cluster_by_anchor
    }

    merged_blocks_by_id: dict[int, LocalActivityBlock] = {}
    merged_events_by_id: dict[int, list[RemoteEventData]] = {}
    merged_order: list[int] = []
    for provisional_id in provisional_order:
        if provisional_id in absorbed_ids:
            continue
        merged_order.append(provisional_id)
        cluster = cluster_by_anchor.get(provisional_id)
        if cluster is not None:
            merged_blocks_by_id[provisional_id] = _merge_cluster_block(provisional_blocks_by_id, cluster)
            merged_events_by_id[provisional_id] = [
                event for member_id in cluster.block_ids for event in provisional_events_by_id[member_id]
            ]
        else:
            merged_blocks_by_id[provisional_id] = provisional_blocks_by_id[provisional_id]
            merged_events_by_id[provisional_id] = provisional_events_by_id[provisional_id]

    surviving_provisional_ids = [
        provisional_id
        for provisional_id in merged_order
        if block_minutes(merged_blocks_by_id[provisional_id]) > 0
    ]
    zero_provisional_ids = [
        provisional_id
        for provisional_id in merged_order
        if block_minutes(merged_blocks_by_id[provisional_id]) == 0
    ]

    supplemental_by_provisional_id: dict[int, list[LocalActivityBlock]] = {}
    unallocated_supplemental: list[LocalActivityBlock] = []
    for provisional_id in zero_provisional_ids:
        block = merged_blocks_by_id[provisional_id]
        orphaned_events.extend(merged_events_by_id[provisional_id])
        if block.duration.total_seconds() <= 0:
            continue
        candidates = [
            surviving_id
            for surviving_id in surviving_provisional_ids
            if _supplemental_key(merged_blocks_by_id[surviving_id]) == _supplemental_key(block)
            and _block_gap(block, merged_blocks_by_id[surviving_id])
            < timedelta(minutes=MERGE_GAP_THRESHOLD_MINUTES)
        ]
        if not candidates:
            unallocated_supplemental.append(block)
            continue
        target_id = min(
            candidates,
            key=lambda candidate_id: (
                _block_gap(block, merged_blocks_by_id[candidate_id]),
                abs((block.start_time - merged_blocks_by_id[candidate_id].start_time).total_seconds()),
                order_position[candidate_id],
            ),
        )
        supplemental_by_provisional_id.setdefault(target_id, []).append(block)

    blocks_by_id: dict[int, LocalActivityBlock] = {}
    block_events: dict[int, list[RemoteEventData]] = {}
    supplemental_by_block_id: dict[int, list[LocalActivityBlock]] = {}
    for provisional_id in surviving_provisional_ids:
        block_id = len(blocks_by_id) + 1
        blocks_by_id[block_id] = merged_blocks_by_id[provisional_id]
        block_events[block_id] = merged_events_by_id[provisional_id]
        supplements = supplemental_by_provisional_id.get(provisional_id)
        if supplements:
            supplemental_by_block_id[block_id] = supplements

    overlaps = compute_overlaps(blocks_by_id)

    final_unmatched_events = [*unmatched_events, *orphaned_events]
    event_ids = {event.external_id for events in block_events.values() for event in events}
    event_ids.update(event.external_id for event in final_unmatched_events)

    return EvidenceBundle(
        blocks_by_id=blocks_by_id,
        remote_event_ids=frozenset(event_ids),
        unmatched_events=final_unmatched_events,
        block_events=block_events,
        overlaps=overlaps,
        supplemental_by_block_id=supplemental_by_block_id,
        unallocated_supplemental=unallocated_supplemental,
    )


def render_entry_evidence(block_ids: list[int], bundle: EvidenceBundle, tz: tzinfo = timezone.utc) -> str:
    """Render one entry's allocated blocks and cited events as LLM-facing evidence text."""
    lines: list[str] = []
    for block_id in block_ids:
        block = bundle.blocks_by_id[block_id]
        lines.append(_format_block_line(block_id, block, tz, bundle.overlaps.get(block_id, [])))
        lines.extend(_format_title_line(cluster) for cluster in block.title_digest)
        context_line = _format_context_line(block)
        if context_line is not None:
            lines.append(context_line)
        for supplemental in bundle.supplemental_by_block_id.get(block_id, []):
            lines.extend(_format_supplemental_block(supplemental, tz))
        events = bundle.block_events.get(block_id, [])
        if events:
            lines.extend(_format_event_line(event, tz, EVENT_INDENT) for event in events)
        else:
            lines.append(EVENT_INDENT + NO_MATCHED_EVIDENCE_LINE)
    return "\n".join(lines)
