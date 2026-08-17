"""Delete refresh-token session rows that expired long enough ago to be past their retention window.

Meant to run on a schedule (cron, or whatever runs periodic jobs in the deployment) or by hand:

    python -m scripts.purge_user_sessions --dry-run     # count only, deletes nothing
    python -m scripts.purge_user_sessions

The whole run is wrapped in a Postgres advisory lock, so a second invocation that overlaps the first -- a
duplicated cron entry, or several app instances each running their own schedule -- exits cleanly instead of
racing it. `pg_try_advisory_lock` never waits, so the loser reports "already running" immediately rather than
piling up behind a long purge. The lock is held on a connection of its own, separate from the one doing the
deleting, because a Postgres advisory lock lives for as long as its connection and must outlast every batch.

Every run logs how many rows it removed. Nothing consumes that number today, but if this job ever silently stops
being scheduled, its absence from the logs is the only sign anything is wrong.
"""

import argparse
import logging
import sys

from sqlalchemy import text

from app.auth.constants import SESSION_PURGE_BATCH_SIZE, SESSION_RETENTION_WINDOW_DAYS
from app.auth.retention import count_purgeable_sessions, purge_expired_sessions
from app.db import base  # noqa: F401
from app.db.session import SessionLocal, engine

logger = logging.getLogger("scripts.purge_user_sessions")

PURGE_ADVISORY_LOCK_KEY = 4711088231


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would be deleted, then exit without deleting them.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=SESSION_PURGE_BATCH_SIZE,
        help=f"Rows to delete per batch (default {SESSION_PURGE_BATCH_SIZE}).",
    )
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    return args


def main(argv: list[str] | None = None) -> int:
    """Returns a process exit code: 0 on a completed run, 1 if another run already holds the lock."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    lock_connection = engine.connect()
    try:
        locked = lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY}
        ).scalar()
        if not locked:
            logger.warning("Session purge skipped: another run already holds the advisory lock")
            return 1

        try:
            db = SessionLocal()
            try:
                if args.dry_run:
                    purgeable = count_purgeable_sessions(db)
                    logger.info(
                        "Session purge dry run: %s rows are older than the %s-day retention window "
                        "(nothing deleted)",
                        purgeable, SESSION_RETENTION_WINDOW_DAYS,
                    )
                    return 0

                deleted = purge_expired_sessions(db, batch_size=args.batch_size)
                logger.info(
                    "Session purge complete: %s rows deleted (expired more than %s days ago)",
                    deleted, SESSION_RETENTION_WINDOW_DAYS,
                )
                return 0
            finally:
                db.close()
        finally:
            released = lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY}
            ).scalar()
            if not released:
                logger.error(
                    "Session purge could not release its advisory lock -- the connection holding it was lost "
                    "mid-run, so another run may have been able to start alongside this one"
                )
    finally:
        lock_connection.close()


if __name__ == "__main__":
    sys.exit(main())
