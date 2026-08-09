"""Aggregate classified raw tracker sessions into continuous local activity blocks."""

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Optional

from app.local_activity.classification import SessionCategory
from app.local_activity.constants import CONTEXT_FIELDS, MERGE_GAP_THRESHOLD_MINUTES, MICRO_IDLE_ABSORB_SECONDS

MERGE_GAP_THRESHOLD = timedelta(minutes=MERGE_GAP_THRESHOLD_MINUTES)
PR_TITLE_RE = re.compile(r"(?:pull request|\bpr)\s*#(\d+)", re.IGNORECASE)

DeterministicTopic = tuple[str, str]


@dataclass(frozen=True)
class RawSessionRow:
    """Represent one classified tracker session and its local context.

    `project`, `category`, and the deterministic topic fields determine aggregation. Other context fields are retained
    as evidence only.
    """

    project: Optional[str]
    app: str
    start_time: datetime
    end_time: datetime
    category: SessionCategory
    window_title: Optional[str] = None
    meeting_name: Optional[str] = None
    branch: Optional[str] = None
    project_name: Optional[str] = None
    active_file: Optional[str] = None
    tool: Optional[str] = None
    url: Optional[str] = None
    cwd: Optional[str] = None
    browser: Optional[str] = None
    end_reason: Optional[str] = None
    bundle_id: Optional[str] = None


@dataclass(frozen=True)
class TitleCluster:
    """Represent one exact window title and its observed seconds within a block."""

    title: str
    seconds: float


@dataclass(frozen=True)
class LocalActivityBlock:
    """Represent one aggregated work stretch and its ordered local evidence."""

    project: Optional[str]
    start_time: datetime
    end_time: datetime
    duration: timedelta
    apps: list[str]
    category: SessionCategory
    title_digest: list[TitleCluster] = field(default_factory=list)
    meeting_name: Optional[str] = None
    deterministic_topic: Optional[DeterministicTopic] = None
    branches: list[str] = field(default_factory=list)
    project_names: list[str] = field(default_factory=list)
    active_files: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    cwds: list[str] = field(default_factory=list)
    browsers: list[str] = field(default_factory=list)
    end_reasons: list[str] = field(default_factory=list)
    bundle_ids: list[str] = field(default_factory=list)


@dataclass
class _OpenBlock:
    """Accumulate fields for one in-progress activity block."""

    start: datetime
    end: datetime
    apps: list[str]
    title_seconds: dict[str, float]
    context: dict[str, list[str]]


def _row_seconds(row: RawSessionRow) -> float:
    return (row.end_time - row.start_time).total_seconds()


def _open_block(row: RawSessionRow) -> _OpenBlock:
    title_seconds: dict[str, float] = {}
    title = (row.window_title or "").strip()
    if title:
        title_seconds[title] = _row_seconds(row)
    return _OpenBlock(
        start=row.start_time,
        end=row.end_time,
        apps=[row.app],
        title_seconds=title_seconds,
        context={
            block_attribute: [value] if (value := getattr(row, row_attribute)) else []
            for row_attribute, block_attribute in CONTEXT_FIELDS
        },
    )


def _append_distinct(values: list[str], value: Optional[str]) -> None:
    if value and value not in values:
        values.append(value)


def _extend_block(block: _OpenBlock, row: RawSessionRow) -> None:
    block.end = max(block.end, row.end_time)
    if row.app not in block.apps:
        block.apps.append(row.app)
    for row_attribute, block_attribute in CONTEXT_FIELDS:
        _append_distinct(block.context[block_attribute], getattr(row, row_attribute))
    title = (row.window_title or "").strip()
    if title:
        block.title_seconds[title] = block.title_seconds.get(title, 0) + _row_seconds(row)


def _finalize_block(
    project: Optional[str],
    category: SessionCategory,
    block: _OpenBlock,
    meeting_name: Optional[str] = None,
    deterministic_topic: Optional[DeterministicTopic] = None,
) -> LocalActivityBlock:
    """Create a block from accumulated rows, preserving title seconds and first-seen tie order."""
    title_digest = sorted(
        (
            TitleCluster(title=title, seconds=seconds)
            for title, seconds in block.title_seconds.items()
            if seconds > 0
        ),
        key=lambda cluster: cluster.seconds,
        reverse=True,
    )
    return LocalActivityBlock(
        project=project,
        start_time=block.start,
        end_time=block.end,
        duration=block.end - block.start,
        apps=block.apps,
        category=category,
        title_digest=title_digest,
        meeting_name=meeting_name,
        deterministic_topic=deterministic_topic,
        **block.context,
    )


def _deterministic_topic(row: RawSessionRow) -> Optional[DeterministicTopic]:
    """Return the exact PR, branch, or project-name topic used for grouping."""
    if row.category == SessionCategory.code_review:
        match = PR_TITLE_RE.search(row.window_title or "")
        if match:
            return ("pr", match.group(1))
    if row.branch:
        return ("branch", row.branch)
    if row.project_name:
        return ("project_name", row.project_name)
    return None


def _contiguity_key(row: RawSessionRow) -> Optional[tuple]:
    """Return the contiguity key, or None for named meetings aggregated separately."""
    if row.category == SessionCategory.meeting and row.meeting_name is not None:
        return None
    project = None if row.category == SessionCategory.meeting else row.project
    return (row.category, project, _deterministic_topic(row))


def _merge_contiguous(rows: list[RawSessionRow]) -> list[LocalActivityBlock]:
    """Merge contiguous non-named-meeting rows with the same key.

    Rows must be chronological. Any differently keyed row, including a named meeting, closes the open block.
    """
    blocks: list[LocalActivityBlock] = []
    open_block: Optional[_OpenBlock] = None
    open_key: Optional[tuple] = None

    for row in rows:
        key = _contiguity_key(row)
        if key is None:
            if open_block is not None:
                blocks.append(
                    _finalize_block(
                        open_key[1], open_key[0], open_block, deterministic_topic=open_key[2]
                    )
                )
                open_block = None
                open_key = None
            continue

        if open_block is not None and key == open_key and row.start_time - open_block.end < MERGE_GAP_THRESHOLD:
            _extend_block(open_block, row)
            continue

        if open_block is not None:
            blocks.append(
                _finalize_block(open_key[1], open_key[0], open_block, deterministic_topic=open_key[2])
            )

        open_block = _open_block(row)
        open_key = key

    if open_block is not None:
        blocks.append(_finalize_block(open_key[1], open_key[0], open_block, deterministic_topic=open_key[2]))
    return blocks


def _merge_unlimited_within_day(rows: list[RawSessionRow]) -> list[LocalActivityBlock]:
    """Merge each named meeting into one block per row start-date, regardless of intervening activity."""
    rows_by_day: dict[date, list[RawSessionRow]] = {}
    for row in rows:
        rows_by_day.setdefault(row.start_time.date(), []).append(row)

    blocks: list[LocalActivityBlock] = []
    for day_rows in rows_by_day.values():
        open_block = _open_block(day_rows[0])
        for row in day_rows[1:]:
            _extend_block(open_block, row)
        blocks.append(_finalize_block(None, SessionCategory.meeting, open_block, meeting_name=day_rows[0].meeting_name))
    return blocks


def aggregate_local_activity(rows: list[RawSessionRow]) -> list[LocalActivityBlock]:
    """Aggregate classified rows into continuous activity blocks.

    Named meetings merge by name within each start-date. Other positive-duration rows merge only when adjacent rows
    share `(category, project, deterministic topic)` and their gap is below `MERGE_GAP_THRESHOLD`; a threshold-sized
    gap splits. Zero-duration rows do not affect ordinary aggregation, but named meeting rows may anchor meeting spans.

    Sorts rows by `(start_time, end_time)` and returns blocks by `start_time`. Pure transformation; does not classify.
    """
    if not rows:
        return []

    rows = sorted(rows, key=lambda row: (row.start_time, row.end_time))

    absorbed_rows: list[RawSessionRow] = []
    for row in rows:
        idle_seconds = (row.end_time - row.start_time).total_seconds()
        if row.category == SessionCategory.idle and idle_seconds < MICRO_IDLE_ABSORB_SECONDS:
            if absorbed_rows:
                prev = absorbed_rows[-1]
                absorbed_rows[-1] = replace(
                    prev, end_time=max(prev.end_time, row.end_time)
                )
                continue
        absorbed_rows.append(row)
    rows = absorbed_rows

    named_meeting_rows_by_name: dict[str, list[RawSessionRow]] = {}
    for row in rows:
        if row.category == SessionCategory.meeting and row.meeting_name is not None:
            named_meeting_rows_by_name.setdefault(row.meeting_name, []).append(row)

    blocks: list[LocalActivityBlock] = []
    for meeting_rows in named_meeting_rows_by_name.values():
        blocks.extend(_merge_unlimited_within_day(meeting_rows))

    blocks.extend(_merge_contiguous([row for row in rows if row.end_time > row.start_time]))

    blocks.sort(key=lambda block: block.start_time)
    return blocks
