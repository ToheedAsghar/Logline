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
