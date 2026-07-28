"""Configuration values and validation thresholds used by tracker_sync.

Having these constants centralized avoids hardcoded magic numbers or strings throughout the codebase.
"""

MAX_SESSION_DURATION_HOURS = 18

RETENTION_WINDOW_DAYS = 90

CLOCK_SKEW_TOLERANCE_MINUTES = 5

KNOWN_END_REASONS = frozenset(
    {
        "switch",
        "title_change",
        "idle",
        "sleep",
        "lock",
        "quit",
    }
)

REASON_UNCLOSED_SESSION = (
    "session is not yet closed (ended_at/end_reason missing) -- only closed sessions are eligible for sync"
)
REASON_BLANK_END_REASON = "end_reason must not be blank or whitespace-only"
REASON_MISSING_TIMEZONE = "started_at and ended_at must be timezone-aware"
REASON_ENDED_BEFORE_STARTED = "ended_at is before started_at"
REASON_ENDED_IN_FUTURE = "ended_at is too far in the future"
REASON_EXCEEDS_MAX_DURATION = f"duration is not under {MAX_SESSION_DURATION_HOURS}h"
REASON_DUPLICATE_IN_BATCH = "duplicate id within batch"
REASON_SESSION_UPDATED = "session updated in database"
