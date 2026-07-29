"""Matches local activity blocks to remote events, deterministically.

This is the last step before AI reconciliation, and the last chance for a
wrong match to get made mechanically instead of by a human or a model
weighing context. So the rule is strict on purpose: match only when both the
project identity and the timing line up exactly, else left unmatched rather
than forced together -- an unmatched pair is easy for the next step to
reconcile by hand; a wrong match silently poisons everything downstream with
no way to detect or undo it later.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.local_activity.aggregation import LocalActivityBlock
from app.matching.constants import MATCH_BUFFER_MINUTES

MATCH_BUFFER = timedelta(minutes=MATCH_BUFFER_MINUTES)


@dataclass(frozen=True)
class ResolvedLocalBlock:
    """A LocalActivityBlock paired with the remote project identity already
    resolved for it, per source -- the output of resolution.py's I/O step,
    and the input matching actually works from.

    `remote_identities` maps source name (e.g. "github", "jira", "slack") to
    the resolved remote_project_id for that source, or None if resolution
    couldn't determine one. A None (or missing) entry for a source means
    "never match this block against that source" -- it is never treated as
    a wildcard that matches anything.
    """

    block: LocalActivityBlock
    remote_identities: dict[str, Optional[str]]


@dataclass(frozen=True)
class RemoteEventData:
    """One already-fetched remote event, as plain data -- decoupled from the
    RemoteEvent ORM model so this module has zero database dependency.
    """

    external_id: str
    source: str
    remote_project_id: Optional[str]
    occurred_at: datetime
    event_type: str
    summary: Optional[str] = None


@dataclass(frozen=True)
class MatchedGroup:
    """One local block and every remote event matched to it. A block only
    appears here if it matched at least one event.
    """

    block: LocalActivityBlock
    events: list[RemoteEventData]


@dataclass(frozen=True)
class MatchResult:
    """Everything matching produced. Unmatched blocks and unmatched events
    are both kept, never dropped -- they're separate, valid entries for the
    next pipeline stage (AI reconciliation) to work with.
    """

    matched: list[MatchedGroup]
    unmatched_blocks: list[LocalActivityBlock]
    unmatched_events: list[RemoteEventData]


def _is_match(resolved: ResolvedLocalBlock, event: RemoteEventData) -> bool:
    identity = resolved.remote_identities.get(event.source)
    if identity is None or identity != event.remote_project_id:
        return False

    block = resolved.block
    window_end = block.end_time + MATCH_BUFFER
    return block.start_time <= event.occurred_at < window_end


def match_local_blocks_to_remote_events(
    resolved_blocks: list[ResolvedLocalBlock], remote_events: list[RemoteEventData]
) -> MatchResult:
    """Match resolved local blocks to remote events.

    A block and an event match only when BOTH hold:

      1. The event's remote_project_id exactly equals the identity already
         resolved for that block, for that event's source. If resolution
         found nothing for that source (identity is None), nothing from
         that source can ever match this block -- a missing identity is a
         reason to not match, never a reason to match everything.
      2. The event's occurred_at falls within [block.start_time,
         block.end_time], or up to (but not including) MATCH_BUFFER_MINUTES
         after end_time -- to allow for a commit or action landing shortly
         after active work stopped, while keeping the same strict-exclusive
         boundary convention as aggregation.py's merge-gap threshold: an
         event exactly MATCH_BUFFER_MINUTES after end_time does NOT match.
         This module's whole design leans conservative on purpose
         rather than forcing a match at the exact boundary. There is no
         equivalent buffer before start_time -- an event 5 minutes before a
         block started is not "close enough", it's simply before the block
         began.

    One remote event can match more than one block if both blocks'
    (project, time window) genuinely satisfy the rule above for that event --
    this function doesn't remove an event from consideration after its first
    match, since deduping here would mean silently discarding a second
    legitimate match rather than surfacing it. Equally, one block can match
    any number of events.

    Returns every block that matched at least one event (grouped with all
    of its matches), every block that matched none, and every event that
    matched no block -- nothing is ever silently dropped.
    """

    matched_groups: list[MatchedGroup] = []
    unmatched_blocks: list[LocalActivityBlock] = []
    matched_event_keys: set[tuple[str, str]] = set()

    for resolved in resolved_blocks:
        block_matches = [event for event in remote_events if _is_match(resolved, event)]
        if block_matches:
            matched_groups.append(MatchedGroup(block=resolved.block, events=block_matches))
            matched_event_keys.update((event.source, event.external_id) for event in block_matches)
        else:
            unmatched_blocks.append(resolved.block)

    unmatched_events = [
        event for event in remote_events if (event.source, event.external_id) not in matched_event_keys
    ]

    return MatchResult(matched=matched_groups, unmatched_blocks=unmatched_blocks, unmatched_events=unmatched_events)
