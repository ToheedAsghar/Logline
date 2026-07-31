import type { IntegrationId } from "@/constants/integrations";
import type { Integration } from "../types";
import { apiRequest } from "./client";

export function listIntegrations(): Promise<Integration[]> {
  return apiRequest<Integration[]>("/integrations");
}

// Requests a one-time OAuth authorization URL for the specified source.
// Returns { connect_url } when supported, or throws ApiError (404/501) if not yet available.
export function createConnectLink(source: IntegrationId): Promise<{ connect_url: string }> {
  return apiRequest<{ connect_url: string }>(`/integrations/${source}/connect-link`, { method: "POST" });
}

export function connectIntegration(source: IntegrationId): Promise<{ connect_url: string }> {
  return createConnectLink(source);
}

export function disconnectIntegration(source: IntegrationId): Promise<void> {
  return apiRequest<void>(`/integrations/${source}`, { method: "DELETE" });
}

