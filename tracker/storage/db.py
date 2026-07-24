"""SQLite schema + read/write, isolated so storage can change without touching
watchers or session logic."""

import sqlite3
from typing import Optional

from tracker.constants import _CREATE_OPEN_SESSION, _CREATE_SESSIONS, DB_DIR, DB_PATH
from tracker.session.models import Session


def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_SESSIONS)
    conn.execute(_CREATE_OPEN_SESSION)
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(open_session)").fetchall()]
    if "is_idle" not in cols:
        conn.execute("ALTER TABLE open_session ADD COLUMN is_idle INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn


def insert_open_session(conn: sqlite3.Connection, session: Session) -> None:
    """Mirrors a newly-opened session for crash recovery. Only one row ever exists."""
    conn.execute("DELETE FROM open_session")
    conn.execute(
        """
        INSERT INTO open_session (id, bundle_id, app_name, window_title, started_at, ended_at, is_idle)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.id,
            session.bundle_id,
            session.app_name,
            session.window_title,
            session.started_at,
            session.ended_at,
            int(session.is_idle),
        ),
    )
    conn.commit()


def update_open_session_ended_at(conn: sqlite3.Connection, session_id: str, ended_at: str) -> None:
    """Heartbeat write, keeping the mirror's ended_at timestamp current. Called on a
    timer every HEARTBEAT_INTERVAL_SECONDS via SessionManager._on_heartbeat()."""
    conn.execute("UPDATE open_session SET ended_at = ? WHERE id = ?", (ended_at, session_id))
    conn.commit()


def close_open_session(conn: sqlite3.Connection, session: Session) -> None:
    """Persists the finished session into `sessions` and clears the open_session
    mirror, in one transaction."""
    conn.execute(
        """
        INSERT INTO sessions (id, bundle_id, app_name, window_title, started_at, ended_at, end_reason, is_idle)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.id,
            session.bundle_id,
            session.app_name,
            session.window_title,
            session.started_at,
            session.ended_at,
            session.end_reason,
            int(session.is_idle),
        ),
    )
    conn.execute("DELETE FROM open_session")
    conn.commit()


def seal_dangling_session(conn: sqlite3.Connection) -> Optional[Session]:
    """Called once at startup. If a previous run ended without closing its open
    session (crash or quit), writes it to `sessions` as-is with end_reason='quit'
    and clears the mirror. Returns the sealed Session, or None if there was nothing
    to seal."""
    row = conn.execute("SELECT * FROM open_session").fetchone()
    if row is None:
        return None
    sealed = Session(
        id=row["id"],
        bundle_id=row["bundle_id"],
        app_name=row["app_name"],
        window_title=row["window_title"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        end_reason="quit",
        is_idle=bool(row["is_idle"]) if "is_idle" in row.keys() else False,
    )
    close_open_session(conn, sealed)
    return sealed
