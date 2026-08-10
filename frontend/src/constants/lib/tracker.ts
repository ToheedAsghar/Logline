/** The tracker's sync agent runs every 5 minutes (`SYNC_INTERVAL_SECONDS` in `tracker/constants.py`). */
export const TRACKER_SYNC_INTERVAL_MINUTES = 5;

/**
 * How long without a sync before the UI calls it stale. Several intervals' worth, so a
 * missed run, a closed laptop, or a slow backlog doesn't read as a failure — this is meant
 * to catch sync being genuinely stuck, not to narrate every skipped tick.
 */
export const TRACKER_STALE_AFTER_MINUTES = 30;

/** Poll interval for the status query. Matches the agent's own cadence. */
export const TRACKER_SYNC_POLL_MS = TRACKER_SYNC_INTERVAL_MINUTES * 60_000;
