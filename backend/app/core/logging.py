"""Sets up logging for the whole backend.

Every log line, whether it comes from `structlog` or the older `logging.getLogger(...)` style, ends up printed to
stdout as one JSON line with a timestamp, a level, request info, and secrets stripped out.
"""

import logging
import sys

import structlog

from app.core.redaction import redact_forbidden_fields, scan_for_leak_patterns

SHARED_PROCESSORS = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.ExtraAdder(),
    structlog.processors.format_exc_info,
    redact_forbidden_fields,
    scan_for_leak_patterns,
]


UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi")


def _redirect_uvicorn_logging() -> None:
    """Makes Uvicorn's own logs go through our JSON and redaction setup too.

    By default Uvicorn writes its own logs straight to the console in its own format, skipping our redaction
    checks. This removes Uvicorn's handlers so those logs fall through to the root logger instead.
    """
    for logger_name in UVICORN_LOGGER_NAMES:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def configure_logging(level: int = logging.INFO) -> None:
    """Turns on JSON logging with redaction for the whole app. Call once, early, before the app is built.

    `main.py` calls this before creating the FastAPI app, and that order matters: Uvicorn sets up its own
    logging when it starts, and this function needs to run after that so `_redirect_uvicorn_logging` actually
    wins and stays in charge.

    `level` is the lowest severity that gets logged (INFO by default). `default=str` on the JSON renderer
    means a value that isn't normally JSON-safe, like a datetime, gets turned into a string instead of
    crashing the app.
    """
    structlog.configure(
        processors=[
            *SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(default=str),
        ],
        foreign_pre_chain=SHARED_PROCESSORS,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    _redirect_uvicorn_logging()
