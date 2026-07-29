"""Per-activity context capture: what project, branch, file, meeting or URL a session was actually about.

`resolve_context` is the only entry point watchers/session code should use.
"""

import logging
from typing import Optional

from tracker.context.models import ContextResult, WindowContext
from tracker.context.resolvers import resolver_for
from tracker.redaction import is_redacted

logger = logging.getLogger(__name__)

UNSET = object()

__all__ = ["ContextResult", "WindowContext", "resolve_context"]


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
    cannot reintroduce the leak. Never raises: a resolver blowing up degrades to empty context rather than
    taking down the tracker.
    """
    if is_redacted(bundle_id):
        return ContextResult()
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
    try:
        return resolver_for(bundle_id)(ctx)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        logger.exception("context resolver failed for %s; continuing without context", bundle_id)
        return ContextResult()
