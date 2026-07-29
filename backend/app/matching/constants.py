"""Tuning values for matching local activity blocks to remote events.

Centralized here for the same reason as local_activity/constants.py -- so
these aren't magic numbers buried in matching/resolution logic.
"""

# --- Matching window ---

MATCH_BUFFER_MINUTES = 15

# --- Github Hosts ---
GITHUB_HOSTS = {"github.com"}
