"""Find a known development tool running in a terminal, using process facts only.

This function takes a process ID (PID), not a WindowContext. Terminal titles are redacted because they can contain
command lines and secrets. This resolver reports details for a redacted app, so the title must be impossible to pass in.
`TerminalToolContext` has no field for it. Do not add a title, WindowContext, or other free-text argument. That
would bring back the leak that redaction is meant to prevent.

This path reads OS process information without requiring Accessibility permission. That is intentional.

If there is not exactly one clearly identified foreground tool, return no details and keep full redaction.
"""

import logging
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from tracker.constants import (
    MULTIPLEXER_PROCESS_NAMES, PROC_WALK_MAX_DEPTH, PROC_WALK_MAX_PIDS, SCRIPT_INTERPRETER_NAMES,
    TERMINAL_TOOL_REGISTRY,
)
from tracker.context.git import current_branch, find_project_root
from tracker.context.models import TerminalToolContext
from tracker.context.proc import (
    ProcBsdInfo, bsd_info, child_pids, exec_path_and_argv, is_tty_foreground, working_directory,
)

logger = logging.getLogger(__name__)


def _candidate_names(exec_path: Optional[str], argv: List[str]) -> List[str]:
    """Return the actual executable names to compare with the tool registry.

    Trust the resolved executable path, not a process-controlled argv[0]. For a `#!` script, the kernel reports the
    interpreter, so check only the script path in argv[1]. Do not search the remaining arguments.
    """
    if not exec_path:
        return []
    head = Path(exec_path).name
    if head.lower().endswith(".exe"):
        head = head[:-4]
    names = [head]
    # Note: SCRIPT_INTERPRETER_NAMES is intentionally narrow. Tools wrapped in sh/bash/zsh
    # scripts (e.g. #!/bin/bash /path/to/tool) are not detected by interpreter expansion,
    # though the tool name in argv[1] is still matched if it appears as a bare path. A broader
    # interpreter list would increase false positives; this is a known coverage gap, not a leak.
    if head in SCRIPT_INTERPRETER_NAMES or head.lower().startswith("python"):
        if len(argv) > 1 and argv[1] and not argv[1].startswith("-"):
            names.append(Path(argv[1]).name)
    return names


def _match_tool(names: List[str], registry: Dict[str, FrozenSet[str]]) -> Optional[str]:
    """Return the registry's standard tool name, never the name reported by the process.

    A process can call itself anything. Returning its observed name could put arbitrary text in the record.
    """
    for name in names:
        for tool, signatures in registry.items():
            if name in signatures:
                return tool
    return None


def _inspect_foreground_process(
    pid: int, info: ProcBsdInfo, registry: Dict[str, FrozenSet[str]]
) -> Tuple[Optional[Tuple[str, int, str]], bool]:
    """Return (hit, is_multiplexer) for a foreground process.

    Reads exec_path, argv, and cwd immediately for the PID so the tool label and the working
    directory come from the same process snapshot, closing a TOCTOU race where the PID could be
    reused between identifying it and reading its data later.
    """
    exec_path, argv = exec_path_and_argv(pid)
    names = _candidate_names(exec_path, argv)
    if any(name in MULTIPLEXER_PROCESS_NAMES for name in names):
        return None, True
    tool = _match_tool(names, registry)
    if tool is None:
        return None, False
    cwd = working_directory(pid)
    if not cwd:
        return None, False
    return (tool, info.e_tdev, cwd), False


def _foreground_processes(
    terminal_pid: int, registry: Dict[str, FrozenSet[str]]
) -> Optional[List[Tuple[str, int, str]]]:
    """Return resolved foreground-tool hits, or None if traversal hits a safety limit.

    Each result is `(tool, tty_device, cwd)`. The visited set, depth limit, and total-PID cap
    prevent a bad process tree from hanging the five-second poll. For example, pid 0 can report
    itself as its own child.
    """
    found: List[Tuple[str, int, str]] = []
    seen: Set[int] = set()
    stack: List[Tuple[int, int]] = [(terminal_pid, 0)]
    while stack:
        pid, depth = stack.pop()
        if len(seen) >= PROC_WALK_MAX_PIDS:
            return None
        if pid in seen or depth > PROC_WALK_MAX_DEPTH:
            continue
        seen.add(pid)
        info = bsd_info(pid)
        if info is not None and pid != terminal_pid and is_tty_foreground(info):
            resolved, is_multiplexer = _inspect_foreground_process(pid, info, registry)
            if is_multiplexer:
                return None
            if resolved is not None:
                found.append(resolved)
        for child in child_pids(pid):
            if child not in seen:
                stack.append((child, depth + 1))
    return found


def resolve_terminal_tool(
    terminal_pid: int, registry: Optional[Dict[str, FrozenSet[str]]] = None
) -> Optional[TerminalToolContext]:
    """Return the one known development tool in the terminal's foreground process group, or None for full redaction.

    Return None when no foreground process is known, a terminal multiplexer is in front, more than one terminal
    has a known tool, or the working folder cannot be read. This identifies the terminal's foreground process, not
    necessarily the visible tab or pane. A multiplexer hides its panes, and without reading the title we cannot tell
    which pane has focus.
    """
    registry = TERMINAL_TOOL_REGISTRY if registry is None else registry
    hits = _foreground_processes(terminal_pid, registry)
    if hits is None:
        return None
    if len(hits) != 1 or len({tty for _, tty, _ in hits}) != 1:
        return None

    tool, _, cwd = hits[0]
    return TerminalToolContext(tool=tool, cwd=cwd, branch=_branch_for(cwd))


def _branch_for(cwd: str) -> Optional[str]:
    """Return the current git branch for `cwd` using the shared git helpers."""
    root = find_project_root(Path(cwd))
    return current_branch(root) if root is not None else None


def project_root_for(cwd: str) -> Optional[str]:
    """Return the enclosing repository root for `cwd`, or None if it is not in a repository."""
    root = find_project_root(Path(cwd))
    return str(root) if root is not None else None
