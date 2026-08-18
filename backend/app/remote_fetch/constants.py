"""Tuning values for remote fetching.

Centralized here for the same reason as `local_activity/constants.py` and
`matching/constants.py` -- so these aren't magic numbers buried in per-source
fetch logic.
"""

# --- Incremental fetch window ---

FIRST_FETCH_LOOKBACK_DAYS = 90

# --- Per-source timeouts ---

# Retuned for direct REST calls, not MCP subprocess spin-up (Docker pulls, npx installs) -- these
# budgets used to absorb server startup latency that no longer exists. Estimates based on each
# source's worst-case page count, not live measurement; revisit once real traffic shows actual
# p99s -- see the remote-fetch-mcp-removal proposal's "adjacent issues" section.
SOURCE_TIMEOUT_SECONDS: dict[str, float] = {
    "github": 45.0,
    "jira": 30.0,
    "slack": 60.0,
    "calendar": 20.0,
}
DEFAULT_SOURCE_TIMEOUT_SECONDS = 30.0

# Per-HTTP-request timeout for the httpx.AsyncClient each fetcher uses. Deliberately shorter than
# any SOURCE_TIMEOUT_SECONDS entry, since a source's budget covers many sequential requests
# (pagination across repos/channels), not just one.
HTTP_CLIENT_TIMEOUT_SECONDS = 15.0

# --- Per-source event limits ---

MAX_EVENTS_PER_SOURCE = 500
