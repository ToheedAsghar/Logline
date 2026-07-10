import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteEvent, getTimeline, updateEvent } from "../api/timeline";
import type { DateRange, EventUpdate } from "../types";

export const TIMELINE_KEY = "timeline";

export function useTimeline(dateRange: DateRange) {
  return useQuery({
    queryKey: [TIMELINE_KEY, dateRange],
    queryFn: () => getTimeline(dateRange),
  });
}

export function useUpdateEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: EventUpdate }) => updateEvent(id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TIMELINE_KEY] });
    },
  });
}

export function useDeleteEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteEvent(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TIMELINE_KEY] });
    },
  });
}
