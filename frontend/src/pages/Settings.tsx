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
  const connectedCount = rows.filter((integration) => integration.status === "connected").length;
  const attentionCount = rows.filter((integration) => integration.status === "error").length;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="max-w-[58ch] text-sm text-muted">
          Logline reads work signals from these sources to build your timeline. Connect what you use — nothing is
          ever posted back without your approval.
        </p>
      </div>

      {integrations.isLoading && <Loading label="Loading integrations…" />}
      {integrations.isError && (
        <p className="font-mono text-[11px] text-danger">Couldn&apos;t load integrations — try again.</p>
      )}

      {!integrations.isLoading && !integrations.isError && (
        <div className="flex flex-col gap-3.5">
          <div className="flex items-baseline justify-between gap-3">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-semibold tracking-tight">Connected sources</h2>
              <span className="font-mono text-[11.5px] text-faint">
                {connectedCount}/{rows.length} active
              </span>
            </div>
            {attentionCount > 0 && (
              <span className="font-mono text-[11px] text-danger">
                {attentionCount} need{attentionCount === 1 ? "s" : ""} attention
              </span>
            )}
          </div>
          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
            {rows.map((integration) => (
              <IntegrationCard key={integration.source} integration={integration} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
