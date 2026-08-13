import type { DeviceEnrollOut, TrackerSyncStatus } from "../types";
import { apiRequest } from "./client";

/**
 * Sync freshness for the logged-in user. Distinct from `/tracker/sync/checkpoint`,
 * which authenticates a device token the browser doesn't have.
 */
export function getTrackerSyncStatus(): Promise<TrackerSyncStatus> {
  return apiRequest<TrackerSyncStatus>("/tracker/sync/status");
}

/**
 * Enroll a new tracker device. Returns the raw secret token exactly once.
 */
export function enrollTrackerDevice(name?: string): Promise<DeviceEnrollOut> {
  return apiRequest<DeviceEnrollOut>("/tracker/devices", {
    method: "POST",
    body: { name: name || undefined },
  });
}


