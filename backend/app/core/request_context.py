"""Middleware that gives each request a `request_id` and adds it to every log line from that request.

`generation_id`, a separate id for tracking one reconciliation run, is not part of this module yet -- it
needs a DB table that doesn't exist on `main` yet.
"""

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attaches a `request_id` to every log line made while handling one request.

    Uses the `X-Request-ID` header if the caller sent one, otherwise generates a new one, and always echoes
    it back in the response header. Cleared right after the request finishes, so it never leaks into the
    next, unrelated request handled by the same worker.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
