"""Resolve the active pane's working directory and command for terminal multiplexers.

Terminal titles are redacted, so we cannot read which tmux pane is focused. Instead we ask the
multiplexer directly for the current pane's path and command, which are filesystem/process facts and
carry no command line text. If the multiplexer cannot be queried we fall back to full redaction.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from tracker.constants import MULTIPLEXER_PROCESS_NAMES, RESOLVER_RESCUE_EXCEPTIONS, TERMINAL_TOOL_REGISTRY
from tracker.context.git import current_branch, find_project_root
from tracker.context.models import TerminalToolContext

logger = logging.getLogger(__name__)

TMUX_CANDIDATES = (
    "/opt/homebrew/bin/tmux",
    "/usr/local/bin/tmux",
    "/usr/bin/tmux",
    "/bin/tmux",
)

_tmux_executable_cache: Optional[str] = None


def _tty_path(tty_device: int) -> Optional[str]:
    """Return the /dev/tty* path for a tty device number, or None if it cannot be found."""
    if tty_device == 0xFFFFFFFF:
        return None
    try:
        for entry in os.listdir("/dev"):
            if entry.startswith("tty"):
                path = os.path.join("/dev", entry)
                try:
                    if os.stat(path).st_rdev == tty_device:
                        return path
                except (OSError, ValueError):
                    continue
    except OSError:
        pass
    return None


def _tmux_executable() -> Optional[str]:
    """Return the path to a usable tmux binary, or None.

    launchd gives the tracker a minimal PATH, so a Homebrew tmux in /opt/homebrew/bin or
    /usr/local/bin may not be found. Try the common install locations first, then fall back
    to a PATH lookup. The result is cached for the lifetime of the process.
    """
    global _tmux_executable_cache
    if _tmux_executable_cache is not None:
        return _tmux_executable_cache
    for candidate in TMUX_CANDIDATES:
        if os.access(candidate, os.X_OK):
            _tmux_executable_cache = candidate
            return candidate
    _tmux_executable_cache = shutil.which("tmux")
    return _tmux_executable_cache


def _run_tmux(args: List[str], timeout: float = 1.0) -> Optional[str]:
    """Run a tmux command and return stripped stdout, or None on any failure."""
    executable = _tmux_executable()
    if executable is None:
        logger.debug("tmux executable not found")
        return None
    try:
        result = subprocess.run(
            [executable] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            logger.debug("tmux command failed: %s %s -> %d", executable, args, result.returncode)
            return None
        return result.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("tmux command error: %s %s -> %s", executable, args, exc)
        return None


def _tmux_client_session(tty_path: str) -> Optional[str]:
    """Find the tmux session attached to the client whose TTY matches `tty_path`."""
    listing = _run_tmux(["list-clients", "-F", "#{client_tty}\t#{client_session}"])
    if not listing:
        return None
    for line in listing.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        client_tty, session = parts
        if client_tty == tty_path:
            return session
    return None


def _match_tool(command: str) -> Optional[str]:
    """Return the registry's standard tool name if `command` matches a known terminal tool."""
    base = command.lstrip("-")
    for tool, signatures in TERMINAL_TOOL_REGISTRY.items():
        if base in signatures:
            return tool
    return None


def _resolve_tmux(tty_device: int) -> Optional[TerminalToolContext]:
    """Return the active pane's cwd and canonical tool for the tmux client on `tty_device`."""
    tty_path = _tty_path(tty_device)
    if tty_path is None:
        logger.debug("tmux resolver: could not map tty device %s to a /dev/tty path", tty_device)
        return None
    session = _tmux_client_session(tty_path)
    if session is None:
        logger.debug("tmux resolver: no tmux client session for tty %s", tty_path)
        return None
    raw = _run_tmux(["display-message", "-t", session, "-p", "-F", "#{pane_current_path}\t#{pane_current_command}"])
    if not raw:
        logger.debug("tmux resolver: empty pane info for session %s", session)
        return None
    parts = raw.split("\t", 1)
    if len(parts) != 2:
        logger.debug("tmux resolver: unexpected pane info format for session %s", session)
        return None
    cwd, command = parts
    if not cwd:
        logger.debug("tmux resolver: empty pane cwd for session %s", session)
        return None
    tool = _match_tool(command) if command else None
    root = find_project_root(Path(cwd))
    branch = current_branch(root) if root is not None else None
    logger.debug(
        "tmux resolver: tty=%s session=%s cwd=%s tool=%s project=%s branch=%s",
        tty_path, session, cwd, tool, root, branch,
    )
    return TerminalToolContext(tool=tool, cwd=cwd, branch=branch)


def _multiplexer_name(names: List[str]) -> Optional[str]:
    """Return the recognized multiplexer name from process names, or None."""
    for name in names:
        if name in MULTIPLEXER_PROCESS_NAMES:
            return name
    return None


def resolve_multiplexer(names: List[str], tty_device: int) -> Optional[TerminalToolContext]:
    """Return the active pane's context for a foreground multiplexer, or None."""
    name = _multiplexer_name(names)
    if name is None:
        return None
    try:
        if name == "tmux":
            return _resolve_tmux(tty_device)
        # TODO: screen, zellij, etc.
        return None
    except RESOLVER_RESCUE_EXCEPTIONS:
        logger.exception("multiplexer resolver failed for %s", name)
        return None
