import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { IntegrationId } from "@/constants/integrations";
import { connectIntegration, disconnectIntegration, listIntegrations } from "../api/integrations";

const INTEGRATIONS_KEY = "integrations";

export function useIntegrations() {
  return useQuery({
    queryKey: [INTEGRATIONS_KEY],
    queryFn: listIntegrations,
  });
}

/** Always 501s today (see `connectIntegration`) — `isError`/`error` reflect that
 * until real OAuth lands, not a transport failure. */
export function useConnectIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (source: IntegrationId) => connectIntegration(source),
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
