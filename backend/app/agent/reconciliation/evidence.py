"""Assembles the output of the earlier Phase 4 stages into the evidence message sent to the reconciliation
model.

Reminders are excluded deliberately (merged in code after the model returns) to prevent the model from
reproducing them. Block ids are assigned here so Stage 6 can validate allocations against the exact
measured durations.

Every block now also carries its Pass 1 category and, when it has one, a title digest -- the distinct
window titles seen during the block with their summed minutes (see `LocalActivityBlock.title_digest`).
Title digests are rendered for every category alike; the only redaction that still applies happened
upstream, in the tracker itself (terminal titles are never captured there in the first place -- see
`tracker/redaction.py`). Whether a block's time window overlaps another's is also computed and rendered
here, in code, so the model never has to infer overlap by comparing time ranges across a wall of text -- see
`compute_overlaps`. A run of several short, project-less blocks close together in time is merged into one block
here, in code, instead of leaving that choice to the model -- see `compute_fragment_clusters` and
`_merge_cluster_block`.

Blocks that round to 0 measured minutes are dropped before ids are assigned -- see `build_evidence` --
since `BlockAllocation.minutes` requires a value greater than zero and citing a 0-minute block could
therefore never validate.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from app.local_activity.aggregation import LocalActivityBlock, TitleCluster
from app.local_activity.classification import SessionCategory
from app.local_activity.constants import MERGE_GAP_THRESHOLD_MINUTES
from app.matching.matcher import MatchedGroup, RemoteEventData

BLOCKS_HEADER = (
    "MEASURED TIME BLOCKS\n"
    "These are the only source of time. Every minute you allocate must be charged to a block id below."
)
UNMATCHED_EVENTS_HEADER = (
    "UNMATCHED REMOTE EVENTS\n"
    "No measured local time corresponds to these. Reminders for them already exist -- do not re-raise them."
)
NO_BLOCKS_LINE = "(none -- no local activity was measured)"
NO_UNMATCHED_EVENTS_LINE = "(none)"
NO_MATCHED_EVIDENCE_LINE = "(no matched remote evidence)"
EVENT_INDENT = "    "
TOTAL_MEASURED_TEMPLATE = "Total measured time across all blocks: {minutes} min."

FRAGMENT_CLUSTER_MIN_BLOCKS = 3
FRAGMENT_CLUSTER_MAX_SPAN_MINUTES = 30


@dataclass(frozen=True)
class EvidenceBundle:
    """The rendered evidence message and the block/event ids it contains.

    `blocks_by_id` maps every block id in `user_content` to its block. `remote_event_ids` is every event
    id that appeared (matched and unmatched alike). Both are carried alongside the rendered message so
    Stage 6 can verify citations without re-deriving or re-parsing from the text.
    """

    user_content: str
    blocks_by_id: dict[int, LocalActivityBlock]
    remote_event_ids: frozenset[str]


def _require_aware(moment: datetime, label: str) -> None:
    """Reject naive datetimes, which would be silently read as this process's local time when converted."""
    if moment.tzinfo is None:
        raise ValueError(
            f"build_evidence requires timezone-aware datetimes, but {label} is naive. Attach a tzinfo "
            f"(e.g. timezone.utc) upstream -- rendering a naive datetime here would silently assume this "
            f"process's local timezone and could place the work on the wrong day."
        )


def block_minutes(block: LocalActivityBlock) -> int:
    """Return a block's measured duration in whole minutes, as shown to the model.

    Exposed publicly so Stage 6 can verify allocations against the exact number the model was given.
    """
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
    return line


_TITLE_LINE_BREAKS_RE = re.compile(r"[\r\n]+")


def _sanitize_title(title: str) -> str:
    """Make a window title safe to embed as one rendered line in the evidence message.

    A window title comes straight from whatever page or app the user had open, so it's effectively
    user-controlled text with no validation from the tracker. Without this, a title containing a newline
    could inject what looks like a whole extra evidence line into the prompt (a fake block, event, or
    instruction), and an embedded quote could visually break out of the quoted title text. Newlines collapse
    to a single space; quotes become straight single quotes instead.
    """
    collapsed = _TITLE_LINE_BREAKS_RE.sub(" ", title)
    return collapsed.replace('"', "'")


def _format_title_line(cluster: TitleCluster) -> str:
    return f'{EVENT_INDENT}title | {cluster.minutes} min | "{_sanitize_title(cluster.title)}"'


def compute_overlaps(blocks_by_id: dict[int, LocalActivityBlock]) -> dict[int, list[int]]:
    """Pairwise overlap detection across every block in the bundle, by wall-clock time window.

    Computed here, in code, rather than left for the model to infer: aggregation only ever produces
    overlapping blocks for one deliberate reason -- a Meeting block's span stretches to cover a calendar
    meeting's true duration even when the person tabbed away mid-call (see
    `aggregation.py::_merge_unlimited_within_day`) -- and the model should be told the fact directly rather
    than asked to notice it by comparing time ranges across a wall of text. Stage 6 separately verifies
    that every overlap found here involves a Meeting block -- see
    `verifier.py::_check_unexplained_overlap`.
    """
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
    """A chronologically contiguous run of brief, project-less blocks likely representing one real
    workstream fragmented by per-row Pass 1 classification (e.g. rapid tab/window switching that flips
    the classified category every few seconds without the underlying task actually changing).
    """

    block_ids: list[int]
    span_minutes: int


def compute_fragment_clusters(blocks_by_id: dict[int, LocalActivityBlock]) -> list[FragmentCluster]:
    """Group chronologically adjacent, project-less, non-Meeting blocks into fragment clusters.

    Computed here, in code, from real timestamps -- the same "compute the fact in code, hand the model the
    conclusion" approach as `compute_overlaps` -- rather than asked of the model, which would have to infer
    fragmentation from a wall of near-identical block lines with no ground truth to check itself against.

    Eligibility is `project is None` and `category is not Meeting`: a Meeting's own rules (6-7 in the
    prompt) always take priority and must never be folded into a fragmentation hint. Blocks are walked in
    true chronological order (by start_time), not evidence emission order, since a matched block can sit
    ahead of unmatched ones in the rendered text without being adjacent to them in time.

    A run only becomes a cluster once it reaches `FRAGMENT_CLUSTER_MIN_BLOCKS` blocks -- two adjacent short
    blocks is not fragmentation worth calling out. The run is capped at `FRAGMENT_CLUSTER_MAX_SPAN_MINUTES`:
    once the next block would push the span past the cap, the current run is closed and a new one starts
    with that block, so one long day of scattered activity produces several short, legible clusters rather
    than one meaningless all-day one. A gap of `MERGE_GAP_THRESHOLD_MINUTES` or more between two eligible
    blocks also closes the run, using the same threshold aggregation already merges same-key rows across --
    consistent with what "near-contiguous" means elsewhere in this pipeline. The gap is measured against
    whichever block precedes it in time, even an ineligible one skipped over above, so a substantial
    unrelated block sitting between two otherwise-adjacent eligible ones still correctly breaks the run.

    Returns clusters as block id groupings only -- it never mutates or reorders `blocks_by_id`. The actual merge
    happens afterward, in `build_evidence` via `_merge_cluster_block`, so detection stays a pure function like
    `compute_overlaps`.
    """
    chronological_ids = sorted(blocks_by_id, key=lambda block_id: blocks_by_id[block_id].start_time)

    clusters: list[FragmentCluster] = []
    current: list[int] = []

    def _close_current() -> None:
        if len(current) >= FRAGMENT_CLUSTER_MIN_BLOCKS:
            span = round(
                (blocks_by_id[current[-1]].end_time - blocks_by_id[current[0]].start_time).total_seconds() / 60
            )
            clusters.append(FragmentCluster(block_ids=list(current), span_minutes=span))
        current.clear()

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
            if gap_minutes >= MERGE_GAP_THRESHOLD_MINUTES or span_if_added > FRAGMENT_CLUSTER_MAX_SPAN_MINUTES:
                _close_current()

        current.append(block_id)

    _close_current()
    return clusters


def _merge_cluster_block(blocks_by_id: dict[int, LocalActivityBlock], cluster: FragmentCluster) -> LocalActivityBlock:
    """Merge a fragment cluster's blocks into one synthetic block.

    Duration is the sum of each member's own measured minutes, not the elapsed start-to-end span -- the gaps
    between members are idle time, not work. Category is whichever member has the most duration, ties going to
    whichever came first. Apps and title_digest are unioned across members in chronological order. Project is
    always None, since that's already required for cluster membership.
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

    minutes_by_title: dict[str, int] = {}
    for member in members:
        for title_cluster in member.title_digest:
            minutes_by_title[title_cluster.title] = minutes_by_title.get(title_cluster.title, 0) + title_cluster.minutes
    title_digest = sorted(
        (TitleCluster(title=title, minutes=minutes) for title, minutes in minutes_by_title.items()),
        key=lambda title_cluster: title_cluster.minutes,
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


def build_evidence(
    matched_groups: list[MatchedGroup],
    unmatched_blocks: list[LocalActivityBlock],
    unmatched_events: list[RemoteEventData],
    tz: tzinfo = timezone.utc,
) -> EvidenceBundle:
    """Render Stage 4 output into the user message for the reconciliation call.

    Block ids are assigned 1-based: matched groups' blocks first (in order), then unmatched blocks.
    Unmatched blocks are included because measured time is real even without remote corroboration. A
    block that rounds to 0 measured minutes is excluded entirely and never assigned an id -- it has
    nothing chargeable to offer (`BlockAllocation.minutes` requires a value greater than zero, so citing
    one could never validate) and would only invite the model to try anyway. A matched group whose block
    rounds to 0 minutes still has its events folded into the unmatched-events section rather than lost,
    since the remote evidence itself is real even though the local block isn't chargeable. All datetimes
    are rendered in `tz` (default UTC) and must be timezone-aware.

    Ids go out in two passes. First, provisional ids follow the matched-then-unmatched order above. Then fragment
    clusters are detected and merged into one block each, taking the position of their lowest-numbered member --
    the other members are dropped and never get a final id. Overlaps are computed after merging, so a merged
    block's overlap note reflects its own real time window.
    """

    provisional_blocks_by_id: dict[int, LocalActivityBlock] = {}
    provisional_events_by_id: dict[int, list[RemoteEventData]] = {}
    provisional_order: list[int] = []
    orphaned_events: list[RemoteEventData] = []

    for group in matched_groups:
        if block_minutes(group.block) == 0:
            orphaned_events.extend(group.events)
            continue
        provisional_id = len(provisional_blocks_by_id) + 1
        provisional_blocks_by_id[provisional_id] = group.block
        provisional_events_by_id[provisional_id] = group.events
        provisional_order.append(provisional_id)

    for block in unmatched_blocks:
        if block_minutes(block) == 0:
            continue
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

    blocks_by_id: dict[int, LocalActivityBlock] = {}
    block_events: dict[int, list[RemoteEventData]] = {}
    order: list[int] = []
    for provisional_id in provisional_order:
        if provisional_id in absorbed_ids:
            continue
        block_id = len(blocks_by_id) + 1
        order.append(block_id)
        cluster = cluster_by_anchor.get(provisional_id)
        if cluster is not None:
            blocks_by_id[block_id] = _merge_cluster_block(provisional_blocks_by_id, cluster)
            block_events[block_id] = [
                event for member_id in cluster.block_ids for event in provisional_events_by_id[member_id]
            ]
        else:
            blocks_by_id[block_id] = provisional_blocks_by_id[provisional_id]
            block_events[block_id] = provisional_events_by_id[provisional_id]

    overlaps = compute_overlaps(blocks_by_id)

    block_lines: list[str] = []
    event_ids: set[str] = set()
    for block_id in order:
        block = blocks_by_id[block_id]
        block_lines.append(_format_block_line(block_id, block, tz, overlaps[block_id]))
        block_lines.extend(_format_title_line(cluster) for cluster in block.title_digest)
        events = block_events[block_id]
        if events:
            block_lines.extend(_format_event_line(event, tz, EVENT_INDENT) for event in events)
            event_ids.update(event.external_id for event in events)
        else:
            block_lines.append(EVENT_INDENT + NO_MATCHED_EVIDENCE_LINE)

    if not block_lines:
        block_lines.append(NO_BLOCKS_LINE)

    all_unmatched_events = unmatched_events + orphaned_events
    event_lines = [_format_event_line(event, tz, "") for event in all_unmatched_events]
    event_ids.update(event.external_id for event in all_unmatched_events)
    if not event_lines:
        event_lines.append(NO_UNMATCHED_EVENTS_LINE)

    total_minutes = sum(block_minutes(block) for block in blocks_by_id.values())

    sections = [
        BLOCKS_HEADER,
        "\n".join(block_lines),
        TOTAL_MEASURED_TEMPLATE.format(minutes=total_minutes),
        UNMATCHED_EVENTS_HEADER,
        "\n".join(event_lines),
    ]
    return EvidenceBundle(
        user_content="\n\n".join(sections),
        blocks_by_id=blocks_by_id,
        remote_event_ids=frozenset(event_ids),
    )
