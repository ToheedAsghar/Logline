import type { IntegrationId } from "@/constants/integrations";
import type { Integration } from "../types";
import { apiRequest } from "./client";

export function listIntegrations(): Promise<Integration[]> {
  return apiRequest<Integration[]>("/integrations");
}

// The backend stub (see backend/app/api/integrations.py) always answers 501 —
// real per-source OAuth isn't built yet. Callers (IntegrationCard) are expected
// to catch that via ApiError and render a "not yet available" state rather than
// treating it as an unexpected failure.
export function connectIntegration(source: IntegrationId): Promise<{ detail: string }> {
  return apiRequest<{ detail: string }>(`/integrations/${source}/connect`, { method: "POST" });
}

export function disconnectIntegration(source: IntegrationId): Promise<void> {
  return apiRequest<void>(`/integrations/${source}`, { method: "DELETE" });
}
