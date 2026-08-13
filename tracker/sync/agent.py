"""Scheduled sync run: read closed sessions since the server's checkpoint, upload them in batches, exit.

Stateless by design -- nothing is written locally, so no local state can disagree with the server about what has
been synced. Within a run the cursor advances locally rather than re-reading the checkpoint each batch, since the
server's checkpoint only moves for accepted or duplicate rows and a wholesale-rejected batch would otherwise be
re-read forever instead of paged past.

Run manually with: tracker/.venv/bin/python -m tracker.sync.agent
"""

import logging
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Optional

from tracker.constants import (
    DEVICE_TOKEN_PATH, EXIT_ALREADY_RUNNING, SYNC_ALREADY_RUNNING_MSG, SYNC_BATCH_MSG, SYNC_COMPLETE_MSG,
    SYNC_FAILED_MSG, SYNC_LOCK_PATH, SYNC_NOT_ENROLLED_MSG, SYNC_TOKEN_PERMISSIONS_MSG,
)
from tracker.logging_config import configure_logging
from tracker.singleton import AlreadyRunning, SingleInstanceLock
from tracker.sync import reader
from tracker.sync.client import SyncClient, SyncError
from tracker.sync.config import SyncConfigError, load_config

logger = logging.getLogger(__name__)


def read_device_token(path: Optional[Path] = None) -> Optional[str]:
    """Reads the enrollment token, or returns None when this machine has not been enrolled. Loose permissions warn
    rather than fail, so a fixable file mode does not stop syncing outright."""
    path = path if path is not None else DEVICE_TOKEN_PATH
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not token:
        return None

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(SYNC_TOKEN_PERMISSIONS_MSG, path, mode, path)
    return token


def run_sync(client: SyncClient, conn, batch_size: int) -> int:
    """Uploads every session after the server's checkpoint, oldest first, and returns the number sent.

    The ordering is load-bearing: a run interrupted part way must leave the checkpoint at a contiguous position,
    where newest-first would strand a gap nothing goes back for.
    """
    checkpoint = client.get_checkpoint()
    cursor = reader.cursor_from_checkpoint(checkpoint.last_synced_at)

    sent = 0
    batches = 0
    while True:
        sessions = reader.fetch_batch(conn, cursor, batch_size)
        if not sessions:
            break
        result = client.post_sessions(checkpoint.device_id, sessions)
        logger.info(
            SYNC_BATCH_MSG, len(sessions), result.get("accepted"), result.get("duplicate"), result.get("invalid")
        )
        sent += len(sessions)
        batches += 1
        cursor = reader.advance(sessions)

    logger.info(SYNC_COMPLETE_MSG, sent, batches)
    return sent


def main() -> int:
    configure_logging()

    lock = SingleInstanceLock(SYNC_LOCK_PATH)
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        logger.info(SYNC_ALREADY_RUNNING_MSG, exc)
        return EXIT_ALREADY_RUNNING

    try:
        token = read_device_token()
        if token is None:
            logger.info(SYNC_NOT_ENROLLED_MSG, DEVICE_TOKEN_PATH)
            return 0

        config = load_config()
        client = SyncClient(config.base_url, token, config.timeout_seconds)
        conn = reader.open_read_only()
        try:
            run_sync(client, conn, config.batch_size)
        finally:
            conn.close()
        return 0
    except (SyncError, SyncConfigError, sqlite3.Error, OSError) as exc:
        logger.error(SYNC_FAILED_MSG, exc)
        print(SYNC_FAILED_MSG % exc, file=sys.stderr)
        return 1
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
