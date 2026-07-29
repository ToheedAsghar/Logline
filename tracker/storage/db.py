"""SQLite schema + read/write, isolated so storage can change without touching
watchers or session logic."""

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Optional

from tracker.constants import CONTEXT_COLUMNS, CREATE_OPEN_SESSION, CREATE_SESSIONS, DB_DIR, DB_PATH
from tracker.session.models import Session


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns) -> None:
    """Ad-hoc forward migration for an existing database file: adds any of `columns` the table doesn't have
    yet. The tracker has no migration framework, so new columns must be additive and nullable."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, decl in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


@contextmanager
def _transaction(conn: sqlite3.Connection):
    """Commits on success, rolls back on failure. Without the rollback a failed INSERT would strand the
    DELETE that preceded it in an open transaction on the shared connection."""
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def _encode_context(context_detail: Optional[Dict[str, Any]]) -> Optional[str]:
    """Serializes context_detail for storage. An empty dict is stored as NULL — a session with no resolved
    context should read back as absent, not as an empty object.

    The result is proven UTF-8 encodable before it is returned. A window title truncated mid-surrogate-pair
    yields a lone surrogate that json.dumps accepts but sqlite3 rejects at INSERT time, which would abort
    the write; escaping it keeps the data instead of dropping the whole document.
    """
    if not context_detail:
        return None
    try:
        encoded = json.dumps(context_detail, ensure_ascii=False, sort_keys=True)
        encoded.encode("utf-8")
        return encoded
    except UnicodeEncodeError:
        pass  # subclass of ValueError, so this must be caught first
    except (TypeError, ValueError):
        return None
    try:
        return json.dumps(context_detail, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return None


def _decode_context(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _column(row: sqlite3.Row, name: str, default=None):
    """Reads a column that may predate the current schema on an older database file."""
    return row[name] if name in row.keys() else default


def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(CREATE_SESSIONS)
    conn.execute(CREATE_OPEN_SESSION)
    _add_missing_columns(conn, "open_session", (("is_idle", "INTEGER NOT NULL DEFAULT 0"),) + CONTEXT_COLUMNS)
    _add_missing_columns(conn, "sessions", CONTEXT_COLUMNS)
    conn.commit()
    return conn


def insert_open_session(conn: sqlite3.Connection, session: Session) -> None:
    """Mirrors a newly-opened session for crash recovery. Only one row ever exists."""
    with _transaction(conn):
        conn.execute("DELETE FROM open_session")
        conn.execute(
            """
            INSERT INTO open_session
                (id, bundle_id, app_name, window_title, started_at, ended_at, is_idle,
                 project_path, context_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.bundle_id,
                session.app_name,
                session.window_title,
                session.started_at,
                session.ended_at,
                int(session.is_idle),
                session.project_path,
                _encode_context(session.context_detail),
            ),
        )


def update_open_session_ended_at(conn: sqlite3.Connection, session_id: str, ended_at: str) -> None:
    """Heartbeat write, keeping the mirror's ended_at timestamp current. Called on a
    timer every HEARTBEAT_INTERVAL_SECONDS via SessionManager._on_heartbeat()."""
    with _transaction(conn):
        conn.execute("UPDATE open_session SET ended_at = ? WHERE id = ?", (ended_at, session_id))


def update_open_session_is_idle(conn: sqlite3.Connection, session_id: str, is_idle: bool) -> None:
    """Updates the open_session mirror's is_idle flag when an open session transitions to idle."""
    with _transaction(conn):
        conn.execute("UPDATE open_session SET is_idle = ? WHERE id = ?", (int(is_idle), session_id))


def close_open_session(conn: sqlite3.Connection, session: Session) -> None:
    """Persists the finished session into `sessions` and clears the open_session
    mirror, in one transaction."""
    with _transaction(conn):
        conn.execute(
            """
            INSERT INTO sessions
                (id, bundle_id, app_name, window_title, started_at, ended_at, end_reason, is_idle,
                 project_path, context_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                session.project_path,
                _encode_context(session.context_detail),
            ),
        )
        conn.execute("DELETE FROM open_session")


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
        is_idle=bool(_column(row, "is_idle", False)),
        project_path=_column(row, "project_path"),
        context_detail=_decode_context(_column(row, "context_detail")),
    )
    close_open_session(conn, sealed)
    return sealed
