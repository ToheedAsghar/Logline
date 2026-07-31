"""Collapses fragmented raw local tracker sessions into continuous work blocks.

The local tracker logs a new raw row every time its signal changes -- an app
switch, a terminal focus event, an idle gap closing -- so a single two-hour
work stretch can show up as fifteen or more tiny rows. Nothing downstream
(matching against other sources, AI reconciliation, human review) can make
sense of that granularity. `aggregate_local_activity` is the first step of
the Phase 4 pipeline: it turns those raw rows into the blocks a human would
actually recognize as "I was working on X from 2pm to 4pm."
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.local_activity.constants import MERGE_GAP_THRESHOLD_MINUTES

MERGE_GAP_THRESHOLD = timedelta(minutes=MERGE_GAP_THRESHOLD_MINUTES)


@dataclass(frozen=True)
class RawSessionRow:
    """One fragment of raw tracker activity, already fetched from storage.

    `project` is the exact, literal signal used to decide whether two rows
    belong together -- the working directory or repo path string as recorded
    by the tracker, never inferred or fuzzy-matched. `app` is whichever
    single app/tool was active for this row (e.g. "vscode", "terminal",
    "chrome"); aggregation rolls these up into a per-block list.
    """

    project: str
    app: str
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True)
class LocalActivityBlock:
    """One continuous stretch of work on a single project.

    `apps` lists every distinct app/tool seen during the stretch, in the
    order each first appeared, for the AI to draw on later when writing a
    description of what happened during this block.
    """

    project: str
    start_time: datetime
    end_time: datetime
    duration: timedelta
    apps: list[str]


def _finalize_block(
    project: str, start: datetime, end: datetime, apps: list[str]
) -> LocalActivityBlock:
    """Build a LocalActivityBlock from an in-progress block's accumulated
    state. Pulled out on its own so the two places a block gets closed off
    (mid-loop, on a gap; and after the loop, for the last block) can't drift
    out of sync with each other.
    """

    return LocalActivityBlock(
        project=project,
        start_time=start,
        end_time=end,
        duration=end - start,
        apps=apps,
    )


def aggregate_local_activity(rows: list[RawSessionRow]) -> list[LocalActivityBlock]:
    """Collapse fragmented raw tracker rows into one row per continuous stretch.

    Two rows only ever merge if both hold:

      1. Same project, matched by an exact string comparison on `project`
         (the working directory / repo path as recorded by the tracker).
         Never fuzzy or partial -- a wrong merge here would poison every
         downstream step with no way to detect or undo it later, so any
         ambiguity resolves to keeping rows separate rather than merging.
      2. The gap between the end of one row and the start of the next is
         strictly under MERGE_GAP_THRESHOLD_MINUTES. A gap of exactly 15
         minutes does NOT merge -- "under" means strictly less than, so
         the boundary itself is on the split side, not the merge side.

    Rows are sorted by start_time internally, per project, before merging --
    callers do not need to pre-sort. Raw tracker rows may arrive out of
    order (e.g. read back from an unindexed table), and silently assuming
    sorted input would let a single out-of-order row corrupt a whole block's
    gap calculation.

    This function is pure: no database access, no I/O, no side effects. The
    caller fetches `rows` beforehand and, if ever needed, persists the
    returned blocks afterward -- this only transforms in-memory data.

    Returns one LocalActivityBlock per continuous stretch, sorted by
    start_time across all projects. An empty `rows` list returns an empty
    list.
    """

    if not rows:
        return []

    rows_by_project: dict[str, list[RawSessionRow]] = {}
    for row in rows:
        rows_by_project.setdefault(row.project, []).append(row)

    blocks: list[LocalActivityBlock] = []

    for project, project_rows in rows_by_project.items():
        project_rows.sort(key=lambda row: row.start_time)

        block_start: Optional[datetime] = None
        block_end: Optional[datetime] = None
        block_apps: list[str] = []

        for row in project_rows:
            if block_start is None:
                block_start = row.start_time
                block_end = row.end_time
                block_apps = [row.app]
                continue

            gap = row.start_time - block_end
            if gap < MERGE_GAP_THRESHOLD:
                block_end = max(block_end, row.end_time)
                if row.app not in block_apps:
                    block_apps.append(row.app)
                continue

            blocks.append(_finalize_block(project, block_start, block_end, block_apps))
            block_start = row.start_time
            block_end = row.end_time
            block_apps = [row.app]

        blocks.append(_finalize_block(project, block_start, block_end, block_apps))

    blocks.sort(key=lambda block: block.start_time)
    return blocks
