import type { DateRange, Event } from "../types";
import { apiRequest } from "./client";

export function getTimeline(dateRange: DateRange): Promise<Event[]> {
  return apiRequest<Event[]>("/timeline", { query: { start: dateRange.start, end: dateRange.end } });
}
