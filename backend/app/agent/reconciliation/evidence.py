"""Assembles the output of the earlier Phase 4 stages into the evidence message sent to the reconciliation
model.

Reminders are excluded deliberately (merged in code after the model returns) to prevent the model from
reproducing them. Block ids are assigned here so Stage 6 can validate allocations against the exact
measured durations.
"""

from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo

from app.local_activity.aggregation import LocalActivityBlock
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


def _format_block_line(block_id: int, block: LocalActivityBlock, tz: tzinfo) -> str:
    _require_aware(block.start_time, f"block {block_id} start_time")
    _require_aware(block.end_time, f"block {block_id} end_time")

    start = block.start_time.astimezone(tz)
    end = block.end_time.astimezone(tz)
    apps = ", ".join(block.apps) if block.apps else "none recorded"
    return (
        f"block {block_id} | {start.date().isoformat()} {start:%H:%M}-{end:%H:%M} | "
        f"{block_minutes(block)} min measured | project: {block.project} | apps: {apps}"
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
    Unmatched blocks are included because measured time is real even without remote corroboration.
    All datetimes are rendered in `tz` (default UTC) and must be timezone-aware.
    """

    blocks_by_id: dict[int, LocalActivityBlock] = {}
    block_lines: list[str] = []
    event_ids: set[str] = set()

    for group in matched_groups:
        block_id = len(blocks_by_id) + 1
        blocks_by_id[block_id] = group.block
        block_lines.append(_format_block_line(block_id, group.block, tz))
        if group.events:
            block_lines.extend(_format_event_line(event, tz, EVENT_INDENT) for event in group.events)
            event_ids.update(event.external_id for event in group.events)
        else:
            block_lines.append(EVENT_INDENT + NO_MATCHED_EVIDENCE_LINE)

    for block in unmatched_blocks:
        block_id = len(blocks_by_id) + 1
        blocks_by_id[block_id] = block
        block_lines.append(_format_block_line(block_id, block, tz))
        block_lines.append(EVENT_INDENT + NO_MATCHED_EVIDENCE_LINE)

    if not block_lines:
        block_lines.append(NO_BLOCKS_LINE)

    event_lines = [_format_event_line(event, tz, "") for event in unmatched_events]
    event_ids.update(event.external_id for event in unmatched_events)
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
