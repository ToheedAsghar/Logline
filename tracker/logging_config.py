"""Centralized logging configuration for the tracker.

The tracker runs both as a launchd agent and in foreground developer mode, so the
logging setup must behave correctly in both cases:

- Diagnostic logs are written to rotating files under ``~/Library/Logs/Logline``.
- The human-readable activity/event stream stays on stdout.
- A ``LOGLINE_TRACKER_LOG_STDOUT=1`` environment variable can mirror diagnostics to
  stdout for live terminal debugging.
"""

import logging
import logging.handlers
import os

from tracker import constants

# Rotating file defaults: 10 MB per file, keep 5 backups.
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

_FORMAT = "%(asctime)s %(name)s %(levelname)s: %(message)s"


def configure_logging() -> None:
    """Configure the root logger for tracker diagnostics.

    - INFO and above -> ``~/Library/Logs/Logline/tracker.log``
    - WARNING and above -> ``~/Library/Logs/Logline/tracker.error.log``
    - Optional stdout mirroring via ``LOGLINE_TRACKER_LOG_STDOUT=1``.
    """
    constants.LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FORMAT)

    info_handler = logging.handlers.RotatingFileHandler(
        constants.LOG_DIR / "tracker.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)

    error_handler = logging.handlers.RotatingFileHandler(
        constants.LOG_DIR / "tracker.error.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)

    root = logging.getLogger()
    for old_handler in root.handlers[:]:
        old_handler.close()
    root.handlers.clear()
    root.addHandler(info_handler)
    root.addHandler(error_handler)
    root.setLevel(logging.DEBUG)

    if os.environ.get("LOGLINE_TRACKER_LOG_STDOUT") == "1":
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.DEBUG)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
