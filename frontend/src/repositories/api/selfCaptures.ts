import { apiRequest } from "./client";

export interface SelfCaptureInput {
  text: string;
  timestamp: string;
  linked_gap_id?: number | null;
}

export interface SelfCapture {
  id: number;
  user_id: number;
  text: string;
  timestamp: string;
  linked_gap_id: number | null;
  created_at: string;
}

export function createSelfCapture(data: SelfCaptureInput): Promise<SelfCapture> {
  return apiRequest<SelfCapture>("/self_captures", { method: "POST", body: data });
}
