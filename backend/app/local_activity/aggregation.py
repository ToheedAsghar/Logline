"""Collapses fragmented raw local tracker sessions into continuous work blocks.

The local tracker logs a new raw row every time its signal changes -- an app
switch, a terminal focus event, an idle gap closing -- so a single two-hour
work stretch can show up as fifteen or more tiny rows. Nothing downstream
(matching against other sources, AI reconciliation, human review) can make
sense of that granularity. `aggregate_local_activity` is the first step of
the Phase 4 pipeline: it turns those raw rows into the blocks a human would
actually recognize as "I was working on X from 2pm to 4pm."

Blocks require true chronological contiguity: a run of same-(category,
project) rows only merges into one block while nothing else -- a different
category, a different project -- is seen between them. A block closes the
instant a differently-keyed row appears, even with a zero-second gap;
merging is never decided by filtering rows down to one key first and only
then checking gaps within that filtered subsequence, since that would let a
block's span silently swallow whatever other-key activity happened to sit
between two of its own occurrences. Named meetings are the one deliberate
exception -- see `_merge_unlimited_within_day` for why they merge across any
gap within the same calendar day instead.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Optional

from app.local_activity.classification import SessionCategory
from app.local_activity.constants import MERGE_GAP_THRESHOLD_MINUTES, MICRO_IDLE_ABSORB_SECONDS

MERGE_GAP_THRESHOLD = timedelta(minutes=MERGE_GAP_THRESHOLD_MINUTES)


@dataclass(frozen=True)
class RawSessionRow:
    """One fragment of raw tracker activity, already fetched from storage and already classified.

    `project` is the exact, literal signal used to decide whether two rows belong together -- the working
    directory or repo path string as recorded by the tracker, never inferred or fuzzy-matched. It is None
    for activity with no project context (e.g. most browser tabs), which no longer means the row is
    dropped -- see `category`. `app` is whichever single app/tool was active for this row (e.g. "vscode",
    "terminal", "chrome"); aggregation rolls these up into a per-block list.

    `category` is Pass 1's coarse classification (`app.local_activity.classification.classify_session`),
    assigned by the caller before this row ever reaches aggregation -- this module groups by it but never
    computes it, keeping classification policy out of the pure merge logic. `meeting_name` is only
    meaningful when `category` is `meeting`; it is None for an unnamed meeting.
    """

    project: Optional[str]
    app: str
    start_time: datetime
    end_time: datetime
    category: SessionCategory
    window_title: Optional[str] = None
    meeting_name: Optional[str] = None


@dataclass(frozen=True)
class TitleCluster:
    """One distinct window title seen during a block, with the total minutes spent under it.

    Titles are clustered by exact match only, on the same "never fuzzy or partial" principle as project
    matching below -- two titles that merely look similar are kept as separate clusters rather than guessed
    to be the same thing.
    """

    title: str
    minutes: int


@dataclass(frozen=True)
class LocalActivityBlock:
    """One continuous stretch of work in a single category (and, for non-meeting categories, a single
    project).

    `apps` lists every distinct app/tool seen during the stretch, in the order each first appeared, for the
    AI to draw on later when writing a description of what happened during this block. `title_digest` lists
    every distinct window title seen during the stretch with its summed minutes, most time first -- see
    `TitleCluster`. `meeting_name` carries a Meeting block's name through from `RawSessionRow` (None for an
    unnamed meeting) so matcher.py can check it against a calendar event's title before matching to it.
    """

    project: Optional[str]
    start_time: datetime
    end_time: datetime
    duration: timedelta
    apps: list[str]
    category: SessionCategory
    title_digest: list[TitleCluster] = field(default_factory=list)
    meeting_name: Optional[str] = None


@dataclass
class _OpenBlock:
    """Mutable accumulator for one in-progress block, while merging rows into it."""

    start: datetime
    end: datetime
    apps: list[str]
    title_seconds: dict[str, float]


def _row_seconds(row: RawSessionRow) -> float:
    return (row.end_time - row.start_time).total_seconds()


def _open_block(row: RawSessionRow) -> _OpenBlock:
    title_seconds: dict[str, float] = {}
    title = (row.window_title or "").strip()
    if title:
        title_seconds[title] = _row_seconds(row)
    return _OpenBlock(start=row.start_time, end=row.end_time, apps=[row.app], title_seconds=title_seconds)


def _extend_block(block: _OpenBlock, row: RawSessionRow) -> None:
    block.end = max(block.end, row.end_time)
    if row.app not in block.apps:
        block.apps.append(row.app)
    title = (row.window_title or "").strip()
    if title:
        block.title_seconds[title] = block.title_seconds.get(title, 0) + _row_seconds(row)


def _finalize_block(
    project: Optional[str], category: SessionCategory, block: _OpenBlock, meeting_name: Optional[str] = None
) -> LocalActivityBlock:
    """Build a LocalActivityBlock from an in-progress block's accumulated state.

    Pulled out on its own so the several places a block gets closed off can't drift out of sync with each
    other. Title clusters accumulate raw seconds across every row and round to minutes once, here, at the
    end -- rounding per row first (as this used to) could zero out a title made up entirely of sub-30-second
    rows even though their real combined total exceeds a minute. A title that still rounds to 0 minutes
    after that real accumulation is dropped entirely, the same as a 0-minute block has nothing chargeable to
    offer elsewhere in this pipeline. Clusters are sorted by minutes descending (most time first); ties keep
    first-seen order, since `dict` preserves insertion order and Python's sort is stable.
    """

    rounded_titles = ((title, round(seconds / 60)) for title, seconds in block.title_seconds.items())
    title_digest = sorted(
        (TitleCluster(title=title, minutes=minutes) for title, minutes in rounded_titles if minutes > 0),
        key=lambda cluster: cluster.minutes,
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
    )


def _contiguity_key(row: RawSessionRow) -> Optional[tuple]:
    """The (category, project) key used to decide whether two rows belong to the same block.

    Returns None for named-meeting rows, since those never open or extend a block here -- they are
    aggregated separately by meeting name (see `_merge_unlimited_within_day`). A None row still closes
    whatever block is currently open when encountered in `_merge_contiguous`, since real, differently
    categorized activity happened during it.
    """
    if row.category == SessionCategory.meeting and row.meeting_name is not None:
        return None
    project = None if row.category == SessionCategory.meeting else row.project
    return (row.category, project)


def _merge_contiguous(rows: list[RawSessionRow]) -> list[LocalActivityBlock]:
    """Merge every non-named-meeting row into blocks that are truly contiguous in wall-clock time.

    `rows` must be every row (named-meeting rows included) sorted by start_time, not pre-filtered to one
    category or project -- a block only extends across a gap under MERGE_GAP_THRESHOLD_MINUTES when the
    very next row chronologically shares its (category, project) key; any other row, including a
    named-meeting row, closes it immediately regardless of gap size. Named-meeting rows are skipped for
    block emission (see `_contiguity_key`) but still close an open block on the way past.
    """

    blocks: list[LocalActivityBlock] = []
    open_block: Optional[_OpenBlock] = None
    open_key: Optional[tuple] = None

    for row in rows:
        key = _contiguity_key(row)
        if key is None:
            if open_block is not None:
                blocks.append(_finalize_block(open_key[1], open_key[0], open_block))
                open_block = None
                open_key = None
            continue

        if open_block is not None and key == open_key and row.start_time - open_block.end < MERGE_GAP_THRESHOLD:
            _extend_block(open_block, row)
            continue

        if open_block is not None:
            blocks.append(_finalize_block(open_key[1], open_key[0], open_block))

        open_block = _open_block(row)
        open_key = key

    if open_block is not None:
        blocks.append(_finalize_block(open_key[1], open_key[0], open_block))
    return blocks


def _merge_unlimited_within_day(rows: list[RawSessionRow]) -> list[LocalActivityBlock]:
    """Merge every row for one named meeting into a single block per calendar day, regardless of gap size.

    A meeting's tracked span must reflect the whole time the person was on the call, not just the minutes
    the meeting tab happened to be frontmost -- someone who tabs away to code for 20 minutes mid-call and
    tabs back is still in the meeting the whole time. The ordinary gap threshold would incorrectly split
    that into two separate meeting blocks and lose the middle as unattributed time, so named-meeting rows
    merge across any gap instead: the block spans first-instance to last-instance.

    Capped at one block per calendar day (by each row's own `start_time.date()`) so the same meeting name
    recurring on different days never fuses across them. This uses the row's own timezone for the day
    boundary, the same UTC-boundary approach the rest of this pipeline uses today -- a known limitation
    (deferred, see the project's user-local-date-boundary follow-up), not a new one introduced here.

    Rows must already be sorted by start_time.
    """

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
    """Collapse fragmented raw tracker rows into one row per continuous stretch.

    Two independent passes over the same chronologically sorted rows:

      1. Named-meeting rows (category `meeting` with a `meeting_name`) are grouped by that name and merged
         across any gap within the same calendar day -- see `_merge_unlimited_within_day`. A named
         meeting's block is allowed to overlap other blocks (see `_check_unexplained_overlap` in
         `verifier.py`), since the person genuinely was in the meeting the whole time even while other
         activity was frontmost.
      2. Every other row -- including unnamed meetings, which fall back to this conservative rule rather
         than merging unboundedly without a name to disambiguate occurrences -- is merged by
         `_merge_contiguous`: a (category, project) run only merges across a gap strictly under
         MERGE_GAP_THRESHOLD_MINUTES, matched by an exact string comparison on `project` (never fuzzy or
         partial), and only when nothing else -- including a named-meeting row -- was seen in between. A
         gap of exactly the threshold does NOT merge -- "under" means strictly less than, so the boundary
         itself is on the split side, not the merge side.

    Rows are sorted by start_time internally before either pass -- callers do not need to pre-sort. Raw
    tracker rows may arrive out of order (e.g. read back from an unindexed table), and silently assuming
    sorted input would let a single out-of-order row corrupt a whole block's gap calculation.

    This function is pure: no database access, no I/O, no side effects. It also does not classify --
    every row's `category` must already be set by the caller (see `app.local_activity.classification`).
    The caller fetches `rows` beforehand and, if ever needed, persists the returned blocks afterward --
    this only transforms in-memory data.

    Returns one LocalActivityBlock per continuous stretch, sorted by start_time. An empty `rows` list
    returns an empty list.
    """

    if not rows:
        return []

    rows = sorted(rows, key=lambda row: row.start_time)

    # Pass 0: absorb micro-idle sessions (see MICRO_IDLE_ABSORB_SECONDS) into the row right before them.
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

    blocks.extend(_merge_contiguous(rows))

    blocks.sort(key=lambda block: block.start_time)
    return blocks
