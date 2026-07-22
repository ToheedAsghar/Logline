"""Tuning constants — no magic numbers inline elsewhere."""

from pathlib import Path

HEARTBEAT_INTERVAL_SECONDS = 5
TITLE_POLL_INTERVAL_SECONDS = 5
IDLE_CHECK_INTERVAL_SECONDS = 30
IDLE_THRESHOLD_SECONDS = 4 * 60

KNOWN_TERMINAL_BUNDLE_IDS = frozenset(
    {
        "com.apple.Terminal",
        "com.googlecode.iterm2",
        "dev.warp.Warp-Stable",
        "net.kovidgoyal.kitty",
    }
)

DB_DIR = Path.home() / "Library" / "Application Support" / "Logline"
DB_PATH = DB_DIR / "tracker.db"

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    bundle_id    TEXT NOT NULL,
    app_name     TEXT NOT NULL,
    window_title TEXT,
    started_at   TEXT NOT NULL,
    ended_at     TEXT NOT NULL,
    end_reason   TEXT NOT NULL,
    is_idle      INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_OPEN_SESSION = """
CREATE TABLE IF NOT EXISTS open_session (
    id           TEXT PRIMARY KEY,
    bundle_id    TEXT,
    app_name     TEXT,
    window_title TEXT,
    started_at   TEXT,
    ended_at     TEXT
)
"""
