import { Loading } from "@/atoms";
import { IntegrationCard } from "@/molecules";
import { INTEGRATION_SOURCES, type IntegrationId } from "@/constants/integrations";
import { useIntegrations } from "@/repositories/hooks";
import type { Integration } from "@/repositories/types";

/** A row for a source the backend has never created an `integrations` row
 * for yet (the common case pre-OAuth, since `connect` is still a 501 stub —
 * see app/api/integrations.py). Renders identically to a real disconnected
 * integration; `id: -1` is never sent anywhere, `IntegrationCard`'s
 * connect/disconnect mutations key off `source`, not `id`. */
function placeholder(source: IntegrationId): Integration {
  return { id: -1, source, status: "disconnected", last_synced_at: null, created_at: "" };
}

export default function Settings() {
  const integrations = useIntegrations();
  const bySource = new Map((integrations.data ?? []).map((integration) => [integration.source, integration]));
  const rows = INTEGRATION_SOURCES.map((source) => bySource.get(source.id) ?? placeholder(source.id));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted">Connect the tools Logline should gather evidence from.</p>
      </div>

      {integrations.isLoading && <Loading label="Loading integrations…" />}
      {integrations.isError && (
        <p className="font-mono text-[11px] text-danger">Couldn&apos;t load integrations — try again.</p>
      )}

      {!integrations.isLoading && !integrations.isError && (
        <div className="flex flex-col gap-2.5">
          {rows.map((integration) => (
            <IntegrationCard key={integration.source} integration={integration} />
          ))}
        </div>
      )}
    </div>
  );
}
