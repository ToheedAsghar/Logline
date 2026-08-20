import type { RemoteEventList, RemoteEventListParams } from "../types";
import { apiRequest } from "./client";

export function listRemoteEvents(params: RemoteEventListParams = {}): Promise<RemoteEventList> {
  return apiRequest<RemoteEventList>("/remote-events", {
    query: {
      source: params.source,
      date_range_start: params.date_range_start,
      date_range_end: params.date_range_end,
      cursor: params.cursor ?? undefined,
      limit: params.limit,
    },
  });
}

export function triggerRemoteFetch(): Promise<{ status: string }> {
  return apiRequest<{ status: string }>("/remote-fetch/trigger", { method: "POST" });
}
