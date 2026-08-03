"""Tuning constants — no magic numbers inline elsewhere."""

from pathlib import Path
import objc
import re

RESOLVER_RESCUE_EXCEPTIONS = (
    ValueError, TypeError, KeyError, IndexError, AttributeError,
    RuntimeError, OSError, objc.error, re.error
)

HEARTBEAT_INTERVAL_SECONDS = 5
TITLE_POLL_INTERVAL_SECONDS = 5
IDLE_CHECK_INTERVAL_SECONDS = 30
IDLE_THRESHOLD_SECONDS = 4 * 60

WATCHER_ERROR_MSG = "%s raised; tracker continues running"
AX_GRANTED_MSG = "title watcher: Accessibility permission granted, tracking window titles."
AX_NOT_GRANTED_MSG = (
    "title watcher: Accessibility permission not granted — tracking at app level only "
    "(window_title=NULL). Grant it in System Settings > Privacy & Security > Accessibility."
)

UNKNOWN_BUNDLE_ID = "unknown"
UNKNOWN_APP_NAME = "Unknown"

END_REASON_SWITCH = "switch"
END_REASON_TITLE_CHANGE = "title_change"
END_REASON_IDLE = "idle"
END_REASON_SLEEP = "sleep"
END_REASON_LOCK = "lock"
END_REASON_QUIT = "quit"

EVENT_KIND_SWITCH = "switch"
EVENT_KIND_TITLE = "title"
EVENT_KIND_IDLE_START = "idle_start"
EVENT_KIND_IDLE_END = "idle_end"
EVENT_KIND_SLEEP = "sleep"
EVENT_KIND_WAKE = "wake"
EVENT_KIND_LOCK = "lock"
EVENT_KIND_UNLOCK = "unlock"

AX_DOCUMENT_ATTRIBUTE = "AXDocument"

TRACKER_RUNNING_MSG = "tracker running — watching for app switches. Ctrl+C to stop."
REFUSING_TO_START_MSG = "tracker: refusing to start — %s"
SEALED_SESSION_MSG = "sealed dangling session from previous run: %s (%s)"
RESOLVER_ERROR_MSG = "context resolver failed for %s; continuing without context"
AX_READ_ERROR_MSG = "AXDocument read failed for pid %s; continuing without it"
RESOLVER_CAPABILITY_MSG = "context: %d resolver(s) registered (%s), AX document read wired in"

KNOWN_TERMINAL_BUNDLE_IDS = frozenset(
    {
        "com.apple.Terminal",
        "com.googlecode.iterm2",
        "com.mitchellh.ghostty",
        "dev.warp.Warp-Stable",
        "net.kovidgoyal.kitty",
        "org.alacritty",
        "com.github.wez.wezterm",
        "co.zeit.hyper",
    }
)

SCREEN_LOCKED_NOTIFICATION = "com.apple.screenIsLocked"
SCREEN_UNLOCKED_NOTIFICATION = "com.apple.screenIsUnlocked"

DB_DIR = Path.home() / "Library" / "Application Support" / "Logline"
DB_PATH = DB_DIR / "tracker.db"
LOCK_PATH = DB_DIR / "tracker.lock"

EXIT_ALREADY_RUNNING = 75

CONTEXT_COLUMNS = (("project_path", "TEXT"), ("context_detail", "TEXT"),)

CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    bundle_id      TEXT NOT NULL,
    app_name       TEXT NOT NULL,
    window_title   TEXT,
    started_at     TEXT NOT NULL,
    ended_at       TEXT NOT NULL,
    end_reason     TEXT NOT NULL,
    is_idle        INTEGER NOT NULL DEFAULT 0,
    project_path   TEXT,
    context_detail TEXT
)
"""

CREATE_OPEN_SESSION = """
CREATE TABLE IF NOT EXISTS open_session (
    id             TEXT PRIMARY KEY,
    bundle_id      TEXT,
    app_name       TEXT,
    window_title   TEXT,
    started_at     TEXT,
    ended_at       TEXT,
    is_idle        INTEGER NOT NULL DEFAULT 0,
    project_path   TEXT,
    context_detail TEXT
)
"""
