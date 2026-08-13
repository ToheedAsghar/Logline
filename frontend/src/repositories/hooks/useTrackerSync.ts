import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TRACKER_SYNC_POLL_MS } from "@/constants/tracker";
import { enrollTrackerDevice, getTrackerSyncStatus } from "../api/tracker";

export const TRACKER_SYNC_KEY = "tracker-sync-status";

/**
 * Polls rather than fetching once: the point of surfacing this is catching a sync
 * that has silently stopped, which a value frozen at page load would hide.
 */
export function useTrackerSyncStatus() {
  return useQuery({
    queryKey: [TRACKER_SYNC_KEY],
    queryFn: getTrackerSyncStatus,
    refetchInterval: TRACKER_SYNC_POLL_MS,
  });
}

/**
 * Mutation to enroll a new tracker device. Invalidates sync status query on success.
 */
export function useEnrollTrackerDevice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name?: string) => enrollTrackerDevice(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TRACKER_SYNC_KEY] });
    },
  });
}

