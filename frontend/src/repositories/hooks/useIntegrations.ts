import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { IntegrationId } from "@/constants";
import { connectIntegration, disconnectIntegration, listIntegrations } from "../api/integrations";

const INTEGRATIONS_KEY = "integrations";

export function useIntegrations() {
  return useQuery({
    queryKey: [INTEGRATIONS_KEY],
    queryFn: listIntegrations,
  });
}

export function useConnectIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (source: IntegrationId) => {
      const res = await connectIntegration(source);
      if (res?.connect_url) {
        window.location.href = res.connect_url;
      }
      return res;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [INTEGRATIONS_KEY] });
    },
  });
}

export function useDisconnectIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (source: IntegrationId) => disconnectIntegration(source),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [INTEGRATIONS_KEY] });
    },
  });
}
