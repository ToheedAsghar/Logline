import { useMutation, useQueryClient } from "@tanstack/react-query";
import { approveDraft, generateDraft } from "../api/reconciliation";
import type { ReconciliationGenerateParams, WorkLogDraft } from "../types";
import { ENTRIES_KEY } from "./useEntries";

export const RECONCILIATION_KEY = "reconciliation";

export function useGenerateDraft() {
  return useMutation({
    mutationFn: (params: ReconciliationGenerateParams) => generateDraft(params),
  });
}

export function useApproveDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draft: WorkLogDraft) => approveDraft(draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ENTRIES_KEY] });
    },
  });
}
