import type { IntegrationId } from "@/constants/integrations";
import type { Integration } from "../types";
import { apiRequest } from "./client";

export function listIntegrations(): Promise<Integration[]> {
  return apiRequest<Integration[]>("/integrations");
}

// Connect stays a 501 stub on the backend (see backend/app/api/integrations.py) —
// no fetch function for it yet, matching "don't build UI for it yet".

export function disconnectIntegration(source: IntegrationId): Promise<void> {
  return apiRequest<void>(`/integrations/${source}`, { method: "DELETE" });
}
