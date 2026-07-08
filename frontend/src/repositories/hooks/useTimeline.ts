import { useQuery } from "@tanstack/react-query";
import { getTimeline } from "../api/timeline";
import type { DateRange } from "../types";

export const TIMELINE_KEY = "timeline";

export function useTimeline(dateRange: DateRange) {
  return useQuery({
    queryKey: [TIMELINE_KEY, dateRange],
    queryFn: () => getTimeline(dateRange),
  });
}
