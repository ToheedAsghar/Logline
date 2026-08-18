"""Tuning values for remote fetching.

Centralized here for the same reason as `local_activity/constants.py` and
`matching/constants.py` -- so these aren't magic numbers buried in per-source
fetch logic.
"""

# --- Incremental fetch window ---

FIRST_FETCH_LOOKBACK_DAYS = 90

# --- Per-source timeouts ---

SOURCE_TIMEOUT_SECONDS: dict[str, float] = {
    "github": 120.0,
    "jira": 120.0,
    "slack": 90.0,
    "calendar": 90.0,
}
DEFAULT_SOURCE_TIMEOUT_SECONDS = 120.0

# --- Per-source event limits ---

MAX_EVENTS_PER_SOURCE = 500
