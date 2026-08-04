import { useEffect, useState } from "react";
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

  const [callbackNotice, setCallbackNotice] = useState<{ type: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const integration = params.get("integration");
    const status = params.get("status");
    const detail = params.get("detail");

    if (integration && status) {
      const sourceName = INTEGRATION_SOURCES.find((s) => s.id === integration)?.name ?? integration;
      if (status === "connected") {
        setCallbackNotice({
          type: "success",
          message: `Successfully connected ${sourceName}!`,
        });
      } else if (status === "error") {
        setCallbackNotice({
          type: "error",
          message: `Couldn't connect ${sourceName}${detail ? `: ${detail}` : " — authorization failed."}`,
        });
      }

      // Selectively remove only callback params to preserve other query string parameters
      params.delete("integration");
      params.delete("status");
      params.delete("detail");
      const cleanQuery = params.toString();
      const cleanUrl = cleanQuery ? `${window.location.pathname}?${cleanQuery}` : window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
    }
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="max-w-[58ch] text-sm text-muted">
          Logline reads work signals from these sources to build your timeline. Connect what you use — nothing is
          ever posted back without your approval.
        </p>
      </div>

      {callbackNotice && (
        <div
          role="alert"
          aria-live="polite"
          className={`flex items-center justify-between rounded-lg border px-3.5 py-2.5 font-mono text-xs ${
            callbackNotice.type === "success"
              ? "border-accent-soft bg-accent-soft text-accent-dim"
              : "border-danger/40 bg-danger-soft text-danger"
          }`}
        >
          <span>{callbackNotice.message}</span>
          <button
            type="button"
            aria-label="Dismiss notice"
            onClick={() => setCallbackNotice(null)}
            className="ml-3 font-sans text-xs opacity-70 hover:opacity-100 focus:outline-none"
          >
            ✕
          </button>
        </div>
      )}

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
          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
            {rows.map((integration) => (
              <IntegrationCard key={integration.source} integration={integration} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
