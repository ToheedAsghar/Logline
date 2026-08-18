import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approveDraft, discardDraft, generateDraft, getCurrentDraft } from "../api/reconciliation";
import type { ReconciliationApproveParams, ReconciliationGenerateParams } from "../types";
import { ENTRIES_KEY } from "./useEntries";

export const RECONCILIATION_KEY = "reconciliation";

export function useCurrentDraft(params: ReconciliationGenerateParams) {
  return useQuery({
    queryKey: [RECONCILIATION_KEY, params.date_range_start, params.date_range_end],
    queryFn: () => getCurrentDraft(params),
  });
}

export function useGenerateDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: ReconciliationGenerateParams) => generateDraft(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [RECONCILIATION_KEY] });
    },
  });
}

export function useApproveDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: ReconciliationApproveParams) => approveDraft(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ENTRIES_KEY] });
      queryClient.invalidateQueries({ queryKey: [RECONCILIATION_KEY] });
    },
  });
}

export function useDiscardDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draftId: number) => discardDraft(draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ENTRIES_KEY] });
      queryClient.invalidateQueries({ queryKey: [RECONCILIATION_KEY] });
    },
  });
}
