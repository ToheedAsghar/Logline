import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approveEntry, getEntry, listEntries, updateEntry, type ListEntriesParams } from "../api/entries";
import type { EntryUpdate } from "../types";

const ENTRIES_KEY = "entries";

export function useEntries(params: ListEntriesParams = {}) {
  return useQuery({
    queryKey: [ENTRIES_KEY, params],
    queryFn: () => listEntries(params),
  });
}

export function useEntry(id: number) {
  return useQuery({
    queryKey: [ENTRIES_KEY, id],
    queryFn: () => getEntry(id),
  });
}

export function useUpdateEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: EntryUpdate }) => updateEntry(id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ENTRIES_KEY] });
    },
  });
}

export function useApproveEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => approveEntry(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ENTRIES_KEY] });
    },
  });
}
