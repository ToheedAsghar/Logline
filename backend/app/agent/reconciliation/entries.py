"""Form deterministic work-log entries from measured evidence blocks."""

from dataclasses import dataclass
from datetime import date, timezone, tzinfo

from app.agent.reconciliation.constants import (
    FLOORED_TOPIC_KINDS, OVERLAP_REVIEW_REASON_TEMPLATE, TOPIC_ENTRY_MINUTES_FLOOR,
)
from app.agent.reconciliation.evidence import EvidenceBundle, block_minutes
from app.agent.reconciliation.schemas import BlockAllocation, EntryTag
from app.local_activity.aggregation import local_date
from app.local_activity.classification import SessionCategory

CATEGORY_TO_TAG: dict[SessionCategory, EntryTag] = {
    SessionCategory.meeting: EntryTag.meeting,
    SessionCategory.code_review: EntryTag.code_review,
    SessionCategory.coding: EntryTag.coding,
    SessionCategory.documentation: EntryTag.documentation,
    SessionCategory.comms: EntryTag.coordination,
    SessionCategory.admin: EntryTag.operations,
}


@dataclass(frozen=True)
class FormedEntry:
    """Represent one deterministic block allocation, tag, and cited-event grouping."""

    date: date
    project: str | None
    category: SessionCategory
    base_tag: EntryTag
    block_ids: list[int]
    allocations: list[BlockAllocation]
    source_remote_event_ids: list[str]
    review_reason: str | None = None

    @property
    def total_minutes(self) -> int:
        return sum(allocation.minutes for allocation in self.allocations)


def _event_ids(bundle: EvidenceBundle, block_ids: list[int]) -> list[str]:
    ids: list[str] = []
    for block_id in block_ids:
        for event in bundle.block_events.get(block_id, []):
            if event.external_id not in ids:
                ids.append(event.external_id)
    return ids


def _overlap_review_reason(bundle: EvidenceBundle, block_ids: list[int]) -> str | None:
    """Return a review reason when an entry overlaps a block outside its allocation."""
    overlapping_ids = sorted(
        {
            other_id
            for block_id in block_ids
            for other_id in bundle.overlaps.get(block_id, [])
            if other_id not in block_ids
        }
    )
    if not overlapping_ids:
        return None
    return OVERLAP_REVIEW_REASON_TEMPLATE.format(ids=", ".join(str(block_id) for block_id in overlapping_ids))


def form_entries(bundle: EvidenceBundle, tz: tzinfo = timezone.utc) -> list[FormedEntry]:
    """Group bundle blocks into entries ordered by descending allocated minutes.

    Meetings remain separate. Other blocks group by date, project, category, and deterministic topic; short PR and
    branch-topic groups fold into the matching topic-less group.
    """
    meeting_entries: list[FormedEntry] = []
    candidate_groups: dict[
        tuple[date, str | None, SessionCategory, tuple[str, str] | None], list[int]
    ] = {}

    for block_id, block in bundle.blocks_by_id.items():
        if block.category == SessionCategory.meeting:
            meeting_entries.append(
                FormedEntry(
                    date=local_date(block.start_time, tz),
                    project=None,
                    category=SessionCategory.meeting,
                    base_tag=CATEGORY_TO_TAG[SessionCategory.meeting],
                    block_ids=[block_id],
                    allocations=[BlockAllocation(block_id=block_id, minutes=block_minutes(block))],
                    source_remote_event_ids=_event_ids(bundle, [block_id]),
                )
            )
            continue
        key = (
            local_date(block.start_time, tz),
            block.project,
            block.category,
            block.deterministic_topic,
        )
        candidate_groups.setdefault(key, []).append(block_id)

    grouped: dict[tuple[date, str | None, SessionCategory, tuple[str, str] | None], list[int]] = {}
    for key, block_ids in candidate_groups.items():
        topic = key[3]
        candidate_minutes = sum(block_minutes(bundle.blocks_by_id[block_id]) for block_id in block_ids)
        if (
            topic is not None
            and topic[0] in FLOORED_TOPIC_KINDS
            and candidate_minutes < TOPIC_ENTRY_MINUTES_FLOOR
        ):
            key = (key[0], key[1], key[2], None)
        grouped.setdefault(key, []).extend(block_ids)

    grouped_entries = []
    for key, block_ids in grouped.items():
        block_ids = sorted(block_ids, key=lambda block_id: bundle.blocks_by_id[block_id].start_time)
        grouped_entries.append(
            FormedEntry(
                date=key[0],
                project=key[1],
                category=key[2],
                base_tag=CATEGORY_TO_TAG[key[2]],
                block_ids=block_ids,
                allocations=[
                    BlockAllocation(block_id=block_id, minutes=block_minutes(bundle.blocks_by_id[block_id]))
                    for block_id in block_ids
                ],
                source_remote_event_ids=_event_ids(bundle, block_ids),
                review_reason=_overlap_review_reason(bundle, block_ids),
            )
        )

    entries = meeting_entries + grouped_entries
    entries.sort(key=lambda entry: entry.total_minutes, reverse=True)
    return entries
