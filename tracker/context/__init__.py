"""Per-activity context capture: what project, branch, file, meeting or URL a session was actually about.

`resolve_context` is the only entry point watchers/session code should use.
"""

import logging
from typing import Optional

import objc

from tracker.constants import RESOLVER_CAPABILITY_MSG, RESOLVER_ERROR_MSG
from tracker.context.models import ContextResult, WindowContext
from tracker.context.resolvers import REGISTRY, resolver_for
from tracker.redaction import is_redacted

logger = logging.getLogger(__name__)

UNSET = object()

__all__ = ["ContextResult", "WindowContext", "resolve_context", "resolver_capability_summary"]


def resolver_capability_summary() -> str:
    """One-line startup confirmation that the context layer loaded as expected: the resolver registry and the
    AX read it depends on. A process still running an old build would show a stale or missing line here
    instead of only surfacing later as unexplained NULL project_path rows.
    """
    from tracker.context.ax import focused_document_url  # noqa: F401 — import failure alone is diagnostic

    return RESOLVER_CAPABILITY_MSG % (len(REGISTRY), ", ".join(sorted(REGISTRY)))


def resolve_context(
    bundle_id: str,
    app_name: str,
    window_title: Optional[str] = None,
    pid: Optional[int] = None,
    document_url=UNSET,
) -> ContextResult:
    """Resolves context for one frontmost-window observation. Pass `document_url` explicitly to skip the
    Accessibility read (tests do this); otherwise it is read from `pid` when one is given.

    Redacted apps resolve to empty context, checked here rather than at the call site so a future caller
    cannot reintroduce the leak. Never raises: an AX read or resolver blowing up degrades to empty context
    rather than taking down the tracker.
    """
    if is_redacted(bundle_id):
        return ContextResult()
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
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RuntimeError, OSError, objc.error):
        logger.exception(RESOLVER_ERROR_MSG, bundle_id)
        return ContextResult()
