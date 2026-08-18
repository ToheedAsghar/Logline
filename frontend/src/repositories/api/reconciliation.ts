import type {
  DiscardDraftResult,
  Entry,
  ReconciliationApproveParams,
  ReconciliationGenerateParams,
  ReconciliationResult,
} from "../types";
import { ApiError, apiRequest } from "./client";

export async function getCurrentDraft(params: ReconciliationGenerateParams): Promise<ReconciliationResult | null> {
  try {
    return await apiRequest<ReconciliationResult>("/reconciliation/drafts/current", {
      query: {
        date_range_start: params.date_range_start,
        date_range_end: params.date_range_end,
      },
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function generateDraft(params: ReconciliationGenerateParams): Promise<ReconciliationResult> {
  return apiRequest<ReconciliationResult>("/reconciliation/generate", {
    method: "POST",
    body: params,
  });
}

export function approveDraft(params: ReconciliationApproveParams): Promise<Entry[]> {
  return apiRequest<Entry[]>("/reconciliation/approve", {
    method: "POST",
    body: params,
  });
}

export function discardDraft(draftId: number): Promise<DiscardDraftResult> {
  return apiRequest<DiscardDraftResult>(`/reconciliation/drafts/${draftId}/discard`, {
    method: "POST",
  });
}
