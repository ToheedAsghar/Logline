"""Read-only access to the tracker database for sync.

The connection is opened `mode=ro` so this path is structurally incapable of writing to the file the capture
daemon owns. Timestamps are compared with `julianday()` rather than as strings: sessions are stored as
local-offset ISO-8601 while the server checkpoint is UTC, and lexicographic comparison mis-orders the two.

Only the `sessions` table is read, which is why nothing here filters on "closed" -- an in-progress session lives
in the separate `open_session` mirror until it ends.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from tracker.constants import DB_PATH, SYNC_OVERLAP_SECONDS
from tracker.sync.payload import SELECT_COLUMNS, SyncSessionOut

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_BASE_QUERY = f"SELECT {SELECT_COLUMNS} FROM sessions WHERE "
_AFTER_TIMESTAMP = "julianday(ended_at) > julianday(?)"
_AFTER_TIMESTAMP_OR_ID = (
    "(julianday(ended_at) > julianday(?) OR (julianday(ended_at) = julianday(?) AND id > ?))"
)
_ORDER_AND_LIMIT = " ORDER BY julianday(ended_at) ASC, id ASC LIMIT ?"


@dataclass(frozen=True)
class Cursor:
    """Position in the ordered stream of sessions.

    `session_id` makes the cursor a compound key, which matters at a batch boundary: several sessions can share
    one `ended_at`, and a timestamp-only cursor would either skip the rest of that second or re-read it forever.
    """

    ended_at: str
    session_id: Optional[str] = None


def cursor_from_checkpoint(last_synced_at: Optional[datetime]) -> Cursor:
    """Turns the server's high-water mark into a starting cursor, rewound by the overlap window. A device that has
    never synced starts at the epoch, i.e. sends its whole local history.

    The window only has to cover clock drift between this machine and the server -- closed sessions are never
    rewritten locally, and the backend's upsert already makes a re-send harmless. Every second of window costs
    real rows re-transmitted on every run, so it stays comfortably above the backend's clock-skew tolerance and
    no larger.
    """
    if last_synced_at is None:
        return Cursor(ended_at=EPOCH.isoformat())
    return Cursor(ended_at=(last_synced_at - timedelta(seconds=SYNC_OVERLAP_SECONDS)).isoformat())


def open_read_only(path: Optional[Path] = None) -> sqlite3.Connection:
    """Opens the tracker database read-only. Raises sqlite3.OperationalError if the file does not exist -- `mode=ro`
    will not create one, which is the point."""
    path = path if path is not None else DB_PATH
    conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_batch(conn: sqlite3.Connection, cursor: Cursor, limit: int) -> List[SyncSessionOut]:
    """Returns up to `limit` sessions strictly after `cursor`, oldest first."""
    if cursor.session_id is None:
        query = _BASE_QUERY + _AFTER_TIMESTAMP + _ORDER_AND_LIMIT
        params = (cursor.ended_at, limit)
    else:
        query = _BASE_QUERY + _AFTER_TIMESTAMP_OR_ID + _ORDER_AND_LIMIT
        params = (cursor.ended_at, cursor.ended_at, cursor.session_id, limit)
    return [SyncSessionOut.from_row(row) for row in conn.execute(query, params)]


def advance(sessions: List[SyncSessionOut]) -> Cursor:
    """The cursor just past the last session of a batch. Callers only reach here with a non-empty batch."""
    last = sessions[-1]
    return Cursor(ended_at=last.ended_at, session_id=last.id)
