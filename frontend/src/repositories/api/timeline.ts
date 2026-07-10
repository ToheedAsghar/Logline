import type { DateRange, Event, EventUpdate } from "../types";
import { apiRequest } from "./client";

export function getTimeline(dateRange: DateRange): Promise<Event[]> {
  return apiRequest<Event[]>("/timeline", { query: { start: dateRange.start, end: dateRange.end } });
}

export function updateEvent(id: number, patch: EventUpdate): Promise<Event> {
  return apiRequest<Event>(`/timeline/${id}`, { method: "PATCH", body: patch });
}

export function deleteEvent(id: number): Promise<void> {
  return apiRequest<void>(`/timeline/${id}`, { method: "DELETE" });
}
