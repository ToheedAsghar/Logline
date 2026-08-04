"""Find a known development tool running in a terminal, using process facts only.

This function takes a process ID (PID), not a WindowContext. Terminal titles are redacted because they can contain
command lines and secrets. This resolver reports details for a redacted app, so the title must be impossible to pass in.
`TerminalToolContext` has no field for it. Do not add a title, WindowContext, or other free-text argument. That
would bring back the leak that redaction is meant to prevent.

The walk reads OS process information and does not require Accessibility permission. The one exception is
`focused_cwd_provider`, invoked only when foreground processes span more than one TTY: it reads the frontmost
tab's working directory via AX to disambiguate. The recorded cwd always comes from process facts, never from AX.

If focus cannot be determined confidently, return no details and keep full redaction. When multiple TTYs are
active and AX disambiguation fails or is unavailable, the session is fully redacted rather than guessing.
"""

import logging
import os
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple

from tracker.constants import (
    MULTIPLEXER_PROCESS_NAMES, PROC_WALK_MAX_DEPTH, PROC_WALK_MAX_PIDS, SCRIPT_INTERPRETER_NAMES, TERMINAL_BRANCH_KEY,
    TERMINAL_CWD_KEY, TERMINAL_TOOL_KEY, TERMINAL_TOOL_REGISTRY,
)
from tracker.context.git import current_branch, find_project_root
from tracker.context.models import ContextResult, TerminalToolContext
from tracker.context.multiplexer import resolve_multiplexer
from tracker.context.proc import (
    ProcBsdInfo, bsd_info, child_pids, exec_path_and_argv, is_tty_foreground, working_directory,
)

logger = logging.getLogger(__name__)


def _candidate_names(exec_path: Optional[str], argv: List[str]) -> List[str]:
    """Return the actual executable names to compare with the tool registry.

    Trust the resolved executable path, not a process-controlled argv[0]. For a `#!` script, the kernel reports the
    interpreter, so check only the script path in argv[1]. Do not search the remaining arguments.

    `SCRIPT_INTERPRETER_NAMES` is intentionally narrow: tools wrapped in sh/bash/zsh scripts are not detected by
    interpreter expansion, though the tool name in argv[1] still matches when it appears as a bare path. A broader
    interpreter list would increase false positives; this is a known coverage gap, not a leak.
    """
    if not exec_path:
        return []
    head = Path(exec_path).name
    if head.lower().endswith(".exe"):
        head = head[:-4]
    names = [head]
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
) -> Tuple[Optional[Tuple[Optional[str], int, str, Optional[str]]], bool]:
    """Return (hit, is_multiplexer) for a foreground process.

    Reads exec_path, argv, and cwd immediately for the PID so the tool label and the working
    directory come from the same process snapshot, closing a TOCTOU race where the PID could be
    reused between identifying it and reading its data later. A hit is returned even when the
    foreground process is not a known tool (tool=None) so that a plain shell session can still
    contribute its working directory for project attribution. The fourth element is the origin
    cwd, which may be None if the working directory cannot be read.
    """
    exec_path, argv = exec_path_and_argv(pid)
    names = _candidate_names(exec_path, argv)
    origin_cwd = working_directory(pid)
    if any(name in MULTIPLEXER_PROCESS_NAMES for name in names):
        detected = resolve_multiplexer(names, info.e_tdev)
        if detected is not None:
            return (detected.tool, info.e_tdev, detected.cwd, origin_cwd), True
        return None, True
    if not origin_cwd:
        return None, False
    tool = _match_tool(names, registry)
    return (tool, info.e_tdev, origin_cwd, origin_cwd), False


def _foreground_processes(
    terminal_pid: int, registry: Dict[str, FrozenSet[str]]
) -> Optional[List[Tuple[Optional[str], int, str, Optional[str]]]]:
    """Return resolved foreground-process hits, or None if traversal hits a safety limit.

    Each result is `(tool, tty_device, cwd, origin_cwd)`; `tool` may be None for a plain shell and
    `origin_cwd` may be None when unreadable. For a multiplexer, `origin_cwd` is the client's own
    directory before the active-pane substitution — Terminal.app reports that as the focused window's
    cwd because tmux consumes OSC 7 rather than forwarding it. An unqueryable multiplexer hides its
    panes, so the walk fails closed for the whole terminal. The visited set, depth limit, and
    total-PID cap prevent a bad process tree from hanging the five-second poll.
    """
    found: List[Tuple[Optional[str], int, str, Optional[str]]] = []
    seen: Set[int] = set()
    stack: List[Tuple[int, int]] = [(terminal_pid, 0)]
    self_pid = os.getpid()
    while stack:
        pid, depth = stack.pop()
        if len(seen) >= PROC_WALK_MAX_PIDS:
            return None
        if pid in seen or depth > PROC_WALK_MAX_DEPTH:
            continue
        seen.add(pid)
        if pid == self_pid:
            continue
        info = bsd_info(pid)
        if info is not None and pid != terminal_pid and is_tty_foreground(info):
            resolved, is_multiplexer = _inspect_foreground_process(pid, info, registry)
            if is_multiplexer and resolved is None:
                return None
            if resolved is not None:
                found.append(resolved)
        for child in child_pids(pid):
            if child not in seen:
                stack.append((child, depth + 1))
    return found


def resolve_terminal_tool(
    terminal_pid: int,
    registry: Optional[Dict[str, FrozenSet[str]]] = None,
    focused_cwd_provider: Optional[Callable[[], Optional[str]]] = None,
) -> Optional[TerminalToolContext]:
    """Return the foreground process details for a terminal, or None for full redaction.

    A known development tool is reported in `tool` when one is found; otherwise `tool` is None and the cwd/branch
    still reflect the foreground shell or process. When the walk finds foreground processes on more than one TTY,
    `focused_cwd_provider` (if given) is invoked to get the frontmost tab's working directory, which disambiguates
    the active session. The provider is never called in the common single-session case. Return None when nothing
    resolves.
    """
    registry = TERMINAL_TOOL_REGISTRY if registry is None else registry
    hits = _foreground_processes(terminal_pid, registry)
    if hits is None:
        logger.debug("terminal resolver (pid=%s): process traversal hit safety limit or multiplexer", terminal_pid)
        return None
    if focused_cwd_provider is not None and len({tty for _, tty, _, _ in hits}) > 1:
        focused_cwd = focused_cwd_provider()
        if focused_cwd:
            filtered = _filter_focused(hits, focused_cwd)
            if not filtered:
                logger.debug(
                    "terminal resolver (pid=%s): focused cwd %s matched no foreground process",
                    terminal_pid, focused_cwd,
                )
                return None
            hits = filtered
    selected = _select_hit(hits)
    if selected is None:
        logger.debug(
            "terminal resolver (pid=%s): ambiguous foreground state (%d hit(s), %d tty(s))",
            terminal_pid, len(hits), len({tty for _, tty, _, _ in hits}),
        )
        return None

    tool, _, cwd, _ = selected
    branch = _branch_for(cwd)
    logger.debug(
        "terminal resolver (pid=%s): tool=%s cwd=%s branch=%s",
        terminal_pid, tool, cwd, branch,
    )
    return TerminalToolContext(tool=tool, cwd=cwd, branch=branch)


def _filter_focused(
    hits: List[Tuple[Optional[str], int, str, Optional[str]]], focused_cwd: str
) -> List[Tuple[Optional[str], int, str, Optional[str]]]:
    """Restrict hits to those whose origin working directory matches the frontmost tab's."""
    target = os.path.realpath(focused_cwd)
    return [hit for hit in hits if hit[3] and os.path.realpath(hit[3]) == target]


def _select_hit(
    hits: List[Tuple[Optional[str], int, str, Optional[str]]],
) -> Optional[Tuple[Optional[str], int, str, Optional[str]]]:
    """Return the best foreground-process hit, or None when focus cannot be determined."""
    ttys = {tty for _, tty, _, _ in hits}
    if len(ttys) != 1:
        return None
    if len(hits) == 1:
        return hits[0]
    tool_hits = [hit for hit in hits if hit[0] is not None]
    return tool_hits[0] if len(tool_hits) == 1 else None


def _branch_for(cwd: str) -> Optional[str]:
    """Return the current git branch for `cwd` using the shared git helpers."""
    root = find_project_root(Path(cwd))
    return current_branch(root) if root is not None else None


def project_root_for(cwd: str) -> Optional[str]:
    """Return the enclosing repository root for `cwd`, or None if it is not in a repository."""
    root = find_project_root(Path(cwd))
    return str(root) if root is not None else None


def terminal_context_result(detected: TerminalToolContext) -> ContextResult:
    """Convert a TerminalToolContext into the shared ContextResult shape."""
    result = ContextResult(project_path=project_root_for(detected.cwd))
    if detected.tool is not None:
        result.set(TERMINAL_TOOL_KEY, detected.tool)
    result.set(TERMINAL_CWD_KEY, detected.cwd)
    result.set(TERMINAL_BRANCH_KEY, detected.branch)
    return result
