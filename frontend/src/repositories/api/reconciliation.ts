import type {
  Entry,
  ReconciliationApproveParams,
  ReconciliationGenerateParams,
  ReconciliationResult,
} from "../types";
import { apiRequest } from "./client";

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
