"""Tuning values for turning raw local tracker sessions into readable blocks.

Centralized here so the merge threshold below isn't a magic number buried in
aggregation logic -- anyone tuning it later should be able to find and reason
about it in one place.
"""

# --- Block merging ---

MERGE_GAP_THRESHOLD_MINUTES = 15
