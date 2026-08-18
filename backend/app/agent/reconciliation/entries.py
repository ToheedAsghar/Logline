"""Form deterministic work-log entries from measured evidence blocks."""

from dataclasses import dataclass
from datetime import date, timezone, tzinfo

from app.agent.reconciliation.constants import (
    CATEGORY_MERGE_MAX_MINORITY_SHARE, ENTRY_MERGE_GAP_MINUTES, ENTRY_MERGE_MAX_SPAN_MINUTES, ENTRY_MIN_MINUTES,
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
    topic: tuple[str, str] | None = None

    @property
    def total_minutes(self) -> int:
        return sum(allocation.minutes for allocation in self.allocations)


@dataclass(frozen=True)
class EntryFolding:
    """Contain the entries surviving the minimum-duration floor and the minutes no entry could claim."""

    entries: list[FormedEntry]
    residual: list[BlockAllocation]


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


GroupKey = tuple[date, str | None, SessionCategory, tuple[str, str] | None]


def _group_minutes(bundle: EvidenceBundle, block_ids: list[int]) -> int:
    return sum(block_minutes(bundle.blocks_by_id[block_id]) for block_id in block_ids)


def _group_start(bundle: EvidenceBundle, block_ids: list[int]):
    return min(bundle.blocks_by_id[block_id].start_time for block_id in block_ids)


def _merge_minority_categories(
    grouped: dict[GroupKey, list[int]], bundle: EvidenceBundle
) -> dict[GroupKey, list[int]]:
    """Merge same-topic groups that differ only by category when the minority categories are a small share.

    One real task often reads as two categories -- writing a test is Coding, skimming the diff it covers is Code
    Review -- and splitting on category alone turns that into two entries. A shared deterministic topic is what makes
    them the same task, so groups without one never merge, which is what keeps unlabelled work from chaining into a
    mixed blob. Meetings are excluded in both directions so their measured time always stands alone.
    """
    eligible: dict[tuple[date, str | None, tuple[str, str]], list[GroupKey]] = {}
    for key in grouped:
        work_date, project, category, topic = key
        if topic is None or category == SessionCategory.meeting:
            continue
        eligible.setdefault((work_date, project, topic), []).append(key)

    merged: dict[GroupKey, list[int]] = {}
    absorbed: set[GroupKey] = set()
    for keys in eligible.values():
        if len(keys) < 2:
            continue
        total = sum(_group_minutes(bundle, grouped[key]) for key in keys)
        if total <= 0:
            continue
        dominant = min(
            keys,
            key=lambda key: (-_group_minutes(bundle, grouped[key]), _group_start(bundle, grouped[key])),
        )
        minority = total - _group_minutes(bundle, grouped[dominant])
        if minority / total > CATEGORY_MERGE_MAX_MINORITY_SHARE:
            continue
        merged[dominant] = [block_id for key in keys for block_id in grouped[key]]
        absorbed.update(keys)

    return {
        key: merged.get(key, block_ids)
        for key, block_ids in grouped.items()
        if key in merged or key not in absorbed
    }


def form_entries(bundle: EvidenceBundle, tz: tzinfo = timezone.utc) -> list[FormedEntry]:
    """Group bundle blocks into entries ordered by descending allocated minutes.

    Named meetings remain separate, one entry each. Every other block, including an unnamed meeting, groups by date,
    project, category, and deterministic topic; short PR and branch-topic groups fold into the matching topic-less
    group. Dates are the block start read in `tz`.

    Unnamed meetings group rather than staying separate because a desktop meeting client carries no meeting name and
    is interleaved with other apps, so its time arrives as dozens of sub-minute blocks that would each become an entry.
    """
    meeting_entries: list[FormedEntry] = []
    candidate_groups: dict[
        tuple[date, str | None, SessionCategory, tuple[str, str] | None], list[int]
    ] = {}

    for block_id, block in bundle.blocks_by_id.items():
        if block.category == SessionCategory.meeting and block.meeting_name:
            meeting_entries.append(
                FormedEntry(
                    date=local_date(block.start_time, tz),
                    project=None,
                    category=SessionCategory.meeting,
                    base_tag=CATEGORY_TO_TAG[SessionCategory.meeting],
                    block_ids=[block_id],
                    allocations=[BlockAllocation(block_id=block_id, minutes=block_minutes(block))],
                    source_remote_event_ids=_event_ids(bundle, [block_id]),
                    topic=block.deterministic_topic,
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

    grouped = _merge_minority_categories(grouped, bundle)

    grouped_entries = []
    for key, block_ids in grouped.items():
        block_ids = sorted(block_ids, key=lambda block_id: bundle.blocks_by_id[block_id].start_time)
        distinct_topics = {bundle.blocks_by_id[block_id].deterministic_topic for block_id in block_ids}
        entry_topic = key[3] if key[3] is not None else (
            next(iter(distinct_topics)) if len(distinct_topics) == 1 else None
        )
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
                topic=entry_topic,
            )
        )

    entries = meeting_entries + grouped_entries
    entries.sort(key=lambda entry: entry.total_minutes, reverse=True)
    return entries


def _entry_span(entry: FormedEntry, bundle: EvidenceBundle) -> tuple:
    blocks = [bundle.blocks_by_id[block_id] for block_id in entry.block_ids]
    return min(block.start_time for block in blocks), max(block.end_time for block in blocks)


def merge_adjacent_entries(entries: list[FormedEntry], bundle: EvidenceBundle) -> list[FormedEntry]:
    """Merge same-day, same-project, same-category entries that no session break separates.

    Work the person thinks of as one sitting lands in several entries when its topic drifts mid-session. Each
    `(date, project, category)` lane merges only into its own most recent entry, so entries of other categories
    interleaving in time neither merge nor block the merge, while the gap test still measures real elapsed time.

    `ENTRY_MERGE_GAP_MINUTES` is the pipeline's session-break threshold, so a genuine break always ends an entry, and
    `ENTRY_MERGE_MAX_SPAN_MINUTES` caps the result so repeated short gaps cannot creep into an all-day blob. Matching
    category and date are required and Meetings never participate, so no merge can produce a mixed-category or
    multi-day entry.
    """
    ordered = sorted(entries, key=lambda entry: (_entry_span(entry, bundle), str(entry.topic)))

    merged: list[FormedEntry] = []
    lanes: dict[tuple[date, str | None, SessionCategory], int] = {}
    for entry in ordered:
        if entry.category == SessionCategory.meeting:
            merged.append(entry)
            continue

        lane = (entry.date, entry.project, entry.category)
        index = lanes.get(lane)
        if index is not None:
            previous = merged[index]
            previous_start, previous_end = _entry_span(previous, bundle)
            entry_start, entry_end = _entry_span(entry, bundle)
            gap_minutes = (entry_start - previous_end).total_seconds() / 60
            span_minutes = (max(previous_end, entry_end) - previous_start).total_seconds() / 60
            if gap_minutes < ENTRY_MERGE_GAP_MINUTES and span_minutes <= ENTRY_MERGE_MAX_SPAN_MINUTES:
                merged[index] = _rebuild_entry(previous, entry, bundle)
                continue

        lanes[lane] = len(merged)
        merged.append(entry)

    merged.sort(key=lambda entry: entry.total_minutes, reverse=True)
    return merged


def _rebuild_entry(target: FormedEntry, absorbed: FormedEntry, bundle: EvidenceBundle) -> FormedEntry:
    """Return `target` extended with `absorbed`'s blocks, keeping the target's own identity and re-deriving evidence."""
    block_ids = sorted(
        target.block_ids + absorbed.block_ids,
        key=lambda block_id: bundle.blocks_by_id[block_id].start_time,
    )
    return FormedEntry(
        date=target.date,
        project=target.project,
        category=target.category,
        base_tag=target.base_tag,
        block_ids=block_ids,
        allocations=[
            BlockAllocation(block_id=block_id, minutes=block_minutes(bundle.blocks_by_id[block_id]))
            for block_id in block_ids
        ],
        source_remote_event_ids=_event_ids(bundle, block_ids),
        review_reason=_overlap_review_reason(bundle, block_ids),
        topic=target.topic,
    )


def _earliest_start(entry: FormedEntry, bundle: EvidenceBundle):
    return min(bundle.blocks_by_id[block_id].start_time for block_id in entry.block_ids)


def _fold_target(small: FormedEntry, hosts: list[FormedEntry], bundle: EvidenceBundle) -> int | None:
    """Return the index of the entry a sub-floor entry belongs to.

    Prefers the entry sharing its topic, then the nearest entry with the same project and category.
    """
    eligible = [
        index for index, host in enumerate(hosts)
        if host.date == small.date and host.category != SessionCategory.meeting
    ]

    same_topic = [
        index for index in eligible if small.topic is not None and hosts[index].topic == small.topic
    ]
    if same_topic:
        return max(same_topic, key=lambda index: hosts[index].total_minutes)

    same_kind = [
        index for index in eligible
        if hosts[index].project == small.project and hosts[index].category == small.category
    ]
    if same_kind:
        start = _earliest_start(small, bundle)
        return min(same_kind, key=lambda index: abs(_earliest_start(hosts[index], bundle) - start))
    return None


def fold_small_entries(entries: list[FormedEntry], bundle: EvidenceBundle) -> EntryFolding:
    """Fold entries under `ENTRY_MIN_MINUTES` into a related entry, or report their minutes as residual.

    A sub-floor entry joins the entry sharing its topic, else the nearest entry with the same project and category.
    Anything left over becomes residual rather than being forced into an unrelated entry, so its minutes stay counted
    without inventing a home for them. Meetings are exempt in both directions: they are never folded away however
    short, and never absorb other work, so their measured duration always stands alone.
    """
    def is_host(entry: FormedEntry) -> bool:
        return entry.category == SessionCategory.meeting or entry.total_minutes >= ENTRY_MIN_MINUTES

    hosts = [entry for entry in entries if is_host(entry)]
    small = [entry for entry in entries if not is_host(entry)]
    residual: list[BlockAllocation] = []

    for entry in sorted(small, key=lambda candidate: candidate.total_minutes):
        target = _fold_target(entry, hosts, bundle)
        if target is None:
            residual.extend(entry.allocations)
            continue
        hosts[target] = _rebuild_entry(hosts[target], entry, bundle)

    folded = sorted(hosts, key=lambda entry: entry.total_minutes, reverse=True)
    return EntryFolding(entries=folded, residual=residual)
