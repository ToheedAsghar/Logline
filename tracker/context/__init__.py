"""Capture the project, branch, file, meeting, or URL for each activity.

Watchers and session code should use `resolve_context` as the only entry point.
"""

import logging
from typing import Optional

from tracker.constants import (
    RESOLVER_CAPABILITY_MSG, RESOLVER_ERROR_MSG, RESOLVER_RESCUE_EXCEPTIONS, TERMINAL_BRANCH_KEY, TERMINAL_CWD_KEY,
    TERMINAL_TOOL_KEY, TERMINAL_TOOL_REGISTRY,
)
from tracker.context.models import ContextResult, TerminalToolContext, WindowContext
from tracker.context.resolvers import REGISTRY, resolver_for
from tracker.redaction import is_redacted

logger = logging.getLogger(__name__)

UNSET = object()

__all__ = [
    "ContextResult", "TerminalToolContext", "WindowContext", "resolve_context", "resolver_capability_summary",
]


def resolver_capability_summary() -> str:
    """Return a startup line that confirms the context resolvers and AX read loaded.

    This makes an old or incomplete running build visible before it creates rows with missing project paths.
    """
    from tracker.context.ax import focused_document_url  # noqa: F401 — importing it is the check
    from tracker.context.terminal import resolve_terminal_tool  # noqa: F401 — importing it is the check

    return RESOLVER_CAPABILITY_MSG % (
        len(REGISTRY),
        ", ".join(sorted(REGISTRY)),
        len(TERMINAL_TOOL_REGISTRY),
        ", ".join(sorted(TERMINAL_TOOL_REGISTRY)),
    )


def _resolve_redacted_terminal(pid: Optional[int], app_name: str = "terminal") -> ContextResult:
    """Return `{tool, cwd, branch}` for the foreground process, or empty context.

    A redacted app must never expose its title. This function takes only a PID and copies fields from
    `TerminalToolContext`, which has no place for title text. Anything short of one confident match keeps full
    redaction.
    """
    if pid is None:
        logger.debug("redacted terminal context: no pid for %s", app_name)
        return ContextResult()
    try:
        from tracker.context.terminal import project_root_for, resolve_terminal_tool

        detected = resolve_terminal_tool(pid)
    except RESOLVER_RESCUE_EXCEPTIONS:
        logger.exception(RESOLVER_ERROR_MSG, "terminal")
        return ContextResult()
    if detected is None:
        logger.debug("redacted terminal context: no foreground process resolved for %s (pid=%s)", app_name, pid)
        return ContextResult()

    project_path = project_root_for(detected.cwd)
    logger.debug(
        "redacted terminal context for %s (pid=%s): cwd=%s project_path=%s tool=%s branch=%s",
        app_name, pid, detected.cwd, project_path, detected.tool, detected.branch,
    )
    result = ContextResult(project_path=project_path)
    if detected.tool is not None:
        result.set(TERMINAL_TOOL_KEY, detected.tool)
    result.set(TERMINAL_CWD_KEY, detected.cwd)
    result.set(TERMINAL_BRANCH_KEY, detected.branch)
    return result


def resolve_context(
    bundle_id: str, app_name: str, window_title: Optional[str] = None, pid: Optional[int] = None, document_url=UNSET,
) -> ContextResult:
    """Resolve context for one frontmost-window observation.

    Pass `document_url` to skip the Accessibility read, as tests do. Otherwise read it from `pid` when available.

    Check redacted apps here so future callers cannot send their titles to title-based resolvers. Use
    `_resolve_redacted_terminal`, which sees only the PID and finds `{tool, cwd, branch}` from process data. On
    configured resolver or environment failures, return empty context.
    """
    if is_redacted(bundle_id):
        return _resolve_redacted_terminal(pid, app_name=app_name)
    try:
        if document_url is UNSET:
            document_url = None
            if pid is not None:
                from tracker.context.ax import focused_document_url

                document_url = focused_document_url(pid)

        ctx = WindowContext(
            bundle_id=bundle_id,
            app_name=app_name,
            window_title=window_title,
            document_url=document_url,
        )
        return resolver_for(bundle_id)(ctx)
    except RESOLVER_RESCUE_EXCEPTIONS:
        logger.exception(RESOLVER_ERROR_MSG, bundle_id)
        return ContextResult()
