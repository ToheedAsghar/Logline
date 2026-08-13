import { TRACKER_STALE_AFTER_MINUTES } from "@/constants/tracker";
import { formatRelativeTime } from "@/common/utils";
import type { TrackerSyncStatus } from "@/repositories/types";

function minutesSince(iso: string): number {
  return (Date.now() - new Date(iso).getTime()) / 60_000;
}

/**
 * Sync freshness for the local activity tracker.
 *
 * Exists because the sync agent fails quietly by design — it logs, exits nonzero, and waits
 * for the next interval. Without something in the UI, a tracker that stopped uploading days
 * ago looks exactly like one that had nothing to upload, and the timeline just silently
 * thins out.
 */
export function TrackerSyncNotice({ status }: { status: TrackerSyncStatus }) {
  if (status.device_count === 0) {
    return (
      <p className="font-mono text-[11.5px] text-faint">
        No tracker device enrolled — local activity isn&apos;t being synced.
      </p>
    );
  }

  const isStale = status.last_synced_at === null || minutesSince(status.last_synced_at) > TRACKER_STALE_AFTER_MINUTES;

  return (
    <p
      role={isStale ? "alert" : undefined}
      className={`font-mono text-[11.5px] ${isStale ? "text-danger" : "text-faint"}`}
    >
      {status.last_synced_at === null
        ? "Tracker enrolled, but nothing has synced yet."
        : `Tracker last synced ${formatRelativeTime(status.last_synced_at).toLowerCase()}.`}
      {isStale && " Check that the sync agent is running."}
    </p>
  );
}
