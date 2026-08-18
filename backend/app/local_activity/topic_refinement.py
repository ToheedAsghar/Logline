"""Refine coarse block topics into per-strand topics after aggregation.

Entry formation already splits work wherever a topic exists, so long undifferentiated entries are a topic-resolution
gap rather than a grouping gap. This pass replaces a missing or project-wide topic with one derived from the files a
stretch of work actually touched, leaving precise PR and branch topics alone.

Runs after aggregation on purpose: the title digests and neighbouring blocks it reads do not exist while raw rows are
still being merged, and refining topics there would move block boundaries rather than only regroup entries.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from app.local_activity.aggregation import DeterministicTopic, LocalActivityBlock
from app.local_activity.classification import SessionCategory
from app.local_activity.constants import (
    MAX_TOPIC_STRAND_MINUTES, TOPIC_DOMINANT_FILE_LIMIT, TOPIC_DOMINANT_FILE_SHARE, TOPIC_INHERIT_WINDOW_MINUTES,
    TOPIC_SESSION_GAP_MINUTES, TOPIC_SIGNATURE_FILE_LIMIT,
)

SOURCE_FILE_RE = re.compile(
    r"\b([\w.-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|md|json|jsonl|sql|ya?ml|toml|sh|css|scss|html|rs|go|java|rb"
    r"|log|csv|txt))\b",
    re.IGNORECASE,
)

TIMESTAMP_SUFFIX_RE = re.compile(
    r"[-_.](?:\d{4}-\d{2}-\d{2}|\d{8}|\d{6}|\d{4})(?:[-_tT]?\d{2}[-:]?\d{2}(?:[-:]?\d{2})?)?$"
)

REFINABLE_TOPIC_KINDS = frozenset({"project_name"})
FILE_TOPIC_KIND = "files"
GENERAL_TOPIC_KIND = "general"

BlockEntry = tuple[int, LocalActivityBlock]


@dataclass
class _Strand:
    """Accumulate one run of `(block id, block)` entries judged to be the same piece of work."""

    scope: str
    entries: list[BlockEntry]
    file_seconds: dict[str, float]

    @property
    def minutes(self) -> float:
        return sum(block.duration.total_seconds() for _, block in self.entries) / 60

    @property
    def dominant_files(self) -> set[str]:
        return _dominant_files(self.file_seconds)


def _heaviest(file_seconds: dict[str, float], limit: int) -> list[str]:
    """Return the heaviest file names, breaking ties by name so the result is stable across runs."""
    ranked = sorted(file_seconds.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, _ in ranked[:limit]]


def _dominant_files(file_seconds: dict[str, float]) -> set[str]:
    """Return the files a stretch of work is substantially about, by share of its own file time.

    The share test is what stops chaining: a file glanced at for seconds is not dominant, so it cannot bridge two
    otherwise unrelated stretches that each merely touched it.
    """
    total = sum(file_seconds.values())
    if total <= 0:
        return set()
    dominant = {
        name for name in _heaviest(file_seconds, TOPIC_DOMINANT_FILE_LIMIT)
        if file_seconds[name] / total >= TOPIC_DOMINANT_FILE_SHARE
    }
    return dominant or set(file_seconds)


def normalize_file_name(name: str) -> str:
    """Return a file name with trailing date and time tokens stripped from its stem.

    A rotating artefact like `logs_2026-08-03.md` is the same file each day, so keeping the timestamp would make every
    day's copy a distinct grouping signal. Stripping repeats to catch stacked tokens, and a stem that would normalize
    away entirely is kept as-is rather than collapsing every timestamp-only name onto one identity.
    """
    stem, dot, extension = name.rpartition(".")
    if not dot:
        return name
    stripped = stem
    while True:
        candidate = TIMESTAMP_SUFFIX_RE.sub("", stripped)
        if candidate == stripped:
            break
        stripped = candidate
    if not stripped:
        return name
    return f"{stripped}{dot}{extension}"


def _file_seconds(block: LocalActivityBlock) -> dict[str, float]:
    """Return seconds observed per source file named in the block's window titles, keyed by normalized name."""
    seconds: dict[str, float] = {}
    for cluster in block.title_digest:
        names = {normalize_file_name(name) for name in SOURCE_FILE_RE.findall(cluster.title)}
        for name in names:
            seconds[name] = seconds.get(name, 0.0) + cluster.seconds
    return seconds


def _is_refinable(block: LocalActivityBlock) -> bool:
    """Return whether a block's topic is missing or only project-wide, leaving PR and branch topics untouched."""
    if block.category == SessionCategory.meeting:
        return False
    topic = block.deterministic_topic
    return topic is None or topic[0] in REFINABLE_TOPIC_KINDS


def _scope(block: LocalActivityBlock) -> str:
    """Return the project-wide topic value a block already carries, which strands never cross."""
    topic = block.deterministic_topic
    return topic[1] if topic is not None else ""


def _file_strands(entries: list[BlockEntry]) -> list[_Strand]:
    """Group the entries that name files into strands of shared work.

    An entry continues the current strand when it stays inside the same project scope and its dominant files overlap
    the strand's; requiring dominance on both sides stops a file that either side merely glanced at from chaining
    unrelated work together. A `TOPIC_SESSION_GAP_MINUTES` gap always starts a new strand.
    """
    strands: list[_Strand] = []
    current: _Strand | None = None

    for block_id, block in entries:
        files = _file_seconds(block)
        scope = _scope(block)

        if current is not None:
            gap_minutes = (block.start_time - current.entries[-1][1].end_time).total_seconds() / 60
            if (
                scope != current.scope
                or gap_minutes >= TOPIC_SESSION_GAP_MINUTES
                or not (_dominant_files(files) & current.dominant_files)
            ):
                current = None

        if current is None:
            current = _Strand(scope=scope, entries=[], file_seconds={})
            strands.append(current)

        current.entries.append((block_id, block))
        for name, seconds in files.items():
            current.file_seconds[name] = current.file_seconds.get(name, 0.0) + seconds

    return strands


def _distance_minutes(block: LocalActivityBlock, strand: _Strand) -> float:
    """Return how far a block sits from a strand's nearest edge, in minutes, or 0 while inside it."""
    first_block = strand.entries[0][1]
    last_block = strand.entries[-1][1]
    if block.end_time <= first_block.start_time:
        return (first_block.start_time - block.end_time).total_seconds() / 60
    if block.start_time >= last_block.end_time:
        return (block.start_time - last_block.end_time).total_seconds() / 60
    return 0.0


def _inherit_nearby(quiet: list[BlockEntry], strands: list[_Strand]) -> list[BlockEntry]:
    """Attach each file-less entry to the nearest strand within the inheritance window, returning the leftovers.

    Looking both backwards and forwards matters: a terminal window with no title is just as likely to precede the
    work it belongs to as to follow it.
    """
    orphans: list[BlockEntry] = []
    for block_id, block in quiet:
        candidates = [
            strand for strand in strands
            if strand.scope == _scope(block) and _distance_minutes(block, strand) <= TOPIC_INHERIT_WINDOW_MINUTES
        ]
        if not candidates:
            orphans.append((block_id, block))
            continue
        nearest = min(candidates, key=lambda strand: _distance_minutes(block, strand))
        nearest.entries.append((block_id, block))
        nearest.entries.sort(key=lambda entry: entry[1].start_time)
    return orphans


def _general_strands(entries: list[BlockEntry]) -> list[_Strand]:
    """Group entries that never resolved to files into runs broken only by a real session gap or a scope change."""
    strands: list[_Strand] = []
    current: _Strand | None = None

    for block_id, block in entries:
        scope = _scope(block)
        if current is not None:
            gap_minutes = (block.start_time - current.entries[-1][1].end_time).total_seconds() / 60
            if scope != current.scope or gap_minutes >= TOPIC_SESSION_GAP_MINUTES:
                current = None
        if current is None:
            current = _Strand(scope=scope, entries=[], file_seconds={})
            strands.append(current)
        current.entries.append((block_id, block))

    return strands


def _build_strands(entries: list[BlockEntry]) -> list[_Strand]:
    """Resolve chronological entries into strands: file-derived work first, then inheritance, then general runs."""
    strands = _file_strands([entry for entry in entries if _file_seconds(entry[1])])
    orphans = _inherit_nearby([entry for entry in entries if not _file_seconds(entry[1])], strands)
    strands.extend(_general_strands(orphans))
    strands.sort(key=lambda strand: strand.entries[0][1].start_time)
    return strands


def _largest_gap_index(entries: list[BlockEntry]) -> int:
    """Return the index whose preceding gap is the widest, used as the only place an oversized strand may be cut."""
    return max(
        range(1, len(entries)),
        key=lambda index: (
            entries[index][1].start_time - entries[index - 1][1].end_time,
            -index,
        ),
    )


def _apply_backstop(strand: _Strand) -> list[list[BlockEntry]]:
    """Cut an oversized strand at its widest internal gap until every piece fits the cap.

    Cutting only at a measured gap keeps every piece a real observed boundary; a proportional cut by clock time would
    invent a boundary that nothing in the evidence supports.
    """
    pending = [strand.entries]
    pieces: list[list[BlockEntry]] = []

    while pending:
        piece = pending.pop()
        minutes = sum(block.duration.total_seconds() for _, block in piece) / 60
        if minutes <= MAX_TOPIC_STRAND_MINUTES or len(piece) < 2:
            pieces.append(piece)
            continue
        index = _largest_gap_index(piece)
        pending.append(piece[:index])
        pending.append(piece[index:])

    pieces.sort(key=lambda piece: piece[0][1].start_time)
    return pieces


def _strand_topic(scope: str, file_seconds: dict[str, float], ordinal: int, split: bool) -> DeterministicTopic:
    """Return the topic identifying one strand piece.

    A file-derived topic omits the ordinal so the same work resumed later in the day regroups with itself, while a
    general topic carries it so a real session gap always ends the entry.
    """
    names = _heaviest(file_seconds, TOPIC_SIGNATURE_FILE_LIMIT)
    if names:
        value = "+".join(sorted(names))
        if split:
            value = f"{value}#{ordinal}"
        return (FILE_TOPIC_KIND, f"{scope}:{value}" if scope else value)
    return (GENERAL_TOPIC_KIND, f"{scope}:{ordinal}" if scope else str(ordinal))


def refine_block_topics(blocks: Iterable[BlockEntry]) -> dict[int, LocalActivityBlock]:
    """Return each block id mapped to its block, with missing and project-wide topics replaced by per-strand topics.

    Meeting blocks and blocks already carrying a PR or branch topic are returned unchanged. Every correlation between
    an input block and its output topic goes through the caller-supplied id, never through Python object identity, so
    the result is correct even if a block is copied, cached, or reconstructed anywhere between aggregation and here.
    """
    pairs = list(blocks)
    ordered = sorted(pairs, key=lambda entry: entry[1].start_time)
    strands = _build_strands([entry for entry in ordered if _is_refinable(entry[1])])

    topic_by_id: dict[int, DeterministicTopic] = {}
    ordinal = 0
    for strand in strands:
        pieces = _apply_backstop(strand)
        for piece in pieces:
            ordinal += 1
            piece_seconds: dict[str, float] = {}
            for _, block in piece:
                for name, seconds in _file_seconds(block).items():
                    piece_seconds[name] = piece_seconds.get(name, 0.0) + seconds
            topic = _strand_topic(strand.scope, piece_seconds, ordinal, split=len(pieces) > 1)
            for block_id, _ in piece:
                topic_by_id[block_id] = topic

    return {
        block_id: replace(block, deterministic_topic=topic_by_id[block_id]) if block_id in topic_by_id else block
        for block_id, block in pairs
    }


def refine_blocks_by_id(blocks_by_id: dict[int, LocalActivityBlock]) -> dict[int, LocalActivityBlock]:
    """Return the same block ids mapped to blocks carrying refined topics.

    Applied after evidence building rather than before it: fragment clustering treats a topic change as a reason to
    close a cluster, so richer topics arriving earlier would fragment the evidence and round far more measured time
    away into supplemental.
    """
    return refine_block_topics(blocks_by_id.items())
