"""Detect IDE extension panels (e.g. Claude Code) that bundle a native helper process.

An extension webview has no AXDocument and no tty, so neither the editor resolver nor the terminal
resolver can see it. Some extensions spawn a distinctive native binary under the IDE's process tree;
matching its executable path is the only reliable signal. The walk reads `pbi_comm` for every process
(cheap) and only reads the full executable path for processes whose comm matches a registry entry.
Results are cached briefly because the helper process is long-lived.
"""

import logging
import os
from typing import FrozenSet, Optional, Set

from tracker.constants import (
    IDE_EXTENSION_TOOL_REGISTRY, IDE_EXTENSION_WALK_TTL_SECONDS, PROC_WALK_MAX_DEPTH, PROC_WALK_MAX_PIDS,
)
from tracker.context.git import _ttl_cache
from tracker.context.proc import ProcBsdInfo, bsd_info, child_pids, exec_path_and_argv

logger = logging.getLogger(__name__)

_CANDIDATE_NAMES: FrozenSet[str] = frozenset(
    name for names, _ in IDE_EXTENSION_TOOL_REGISTRY.values() for name in names
)


def _comm(info: ProcBsdInfo) -> str:
    raw = bytes(info.pbi_comm).split(b"\x00", 1)[0]
    return raw.decode("utf-8", "replace")


def _match_extension_tool(comm: str, exec_path: Optional[str]) -> Optional[str]:
    if not exec_path:
        return None
    for tool, (names, signatures) in IDE_EXTENSION_TOOL_REGISTRY.items():
        if comm in names and all(sig in exec_path for sig in signatures):
            return tool
    return None


@_ttl_cache(ttl_seconds=IDE_EXTENSION_WALK_TTL_SECONDS)
def find_ide_extension_tool(ide_pid: int) -> Optional[str]:
    """Return the canonical tool name for a known IDE extension process under `ide_pid`, or None."""
    seen: Set[int] = set()
    stack = [(ide_pid, 0)]
    self_pid = os.getpid()
    while stack:
        pid, depth = stack.pop()
        if len(seen) >= PROC_WALK_MAX_PIDS:
            logger.debug("ide extension walk (pid=%s): traversal hit safety limit", ide_pid)
            return None
        if pid in seen or depth > PROC_WALK_MAX_DEPTH or pid == self_pid:
            continue
        seen.add(pid)
        info = bsd_info(pid)
        if info is not None:
            comm = _comm(info)
            if comm in _CANDIDATE_NAMES:
                exec_path, _ = exec_path_and_argv(pid)
                tool = _match_extension_tool(comm, exec_path)
                if tool is not None:
                    logger.debug("ide extension walk (pid=%s): found %s at pid=%s", ide_pid, tool, pid)
                    return tool
        for child in child_pids(pid):
            if child not in seen:
                stack.append((child, depth + 1))
    return None
