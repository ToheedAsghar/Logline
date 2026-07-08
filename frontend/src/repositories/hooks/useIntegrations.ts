import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { IntegrationId } from "@/constants/integrations";
import { disconnectIntegration, listIntegrations } from "../api/integrations";

const INTEGRATIONS_KEY = "integrations";

export function useIntegrations() {
  return useQuery({
    queryKey: [INTEGRATIONS_KEY],
    queryFn: listIntegrations,
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
