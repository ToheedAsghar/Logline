import { useMemo, useState } from "react";
import { Loading } from "@/atoms";
import { IntegrationCard, TrackerDeviceEnrollment, TrackerSyncNotice } from "@/molecules";

import { INTEGRATION_SOURCES, type IntegrationId } from "@/constants/integrations";
import { useIntegrations, useTrackerSyncStatus } from "@/repositories/hooks";
import type { Integration } from "@/repositories/types";

function placeholder(source: IntegrationId): Integration {
  return { id: -1, source, status: "disconnected", last_synced_at: null, created_at: "" };
}

const ERROR_REASON_MESSAGES: Record<string, string> = {
  denied: "Authorization was denied.",
  expired: "The connection link expired — try again.",
  invalid_state: "The connection request could not be verified — try again.",
  server_error: "Something went wrong on our end — try again.",
};

export default function Settings() {
  const integrations = useIntegrations();
  const trackerSync = useTrackerSyncStatus();

  const bySource = useMemo(() => {
    const map = new Map<IntegrationId, Integration>();
    for (const integration of integrations.data ?? []) {
      map.set(integration.source, integration);
    }
    return map;
  }, [integrations.data]);

  const rows = INTEGRATION_SOURCES.map((source) => bySource.get(source.id) ?? placeholder(source.id));
  const connectedCount = rows.filter((integration) => integration.status === "connected").length;
  const attentionCount = rows.filter((integration) => integration.status === "error").length;

  const [callbackNotice, setCallbackNotice] = useState<{ type: "success" | "error"; message: string } | null>(() => {
    if (typeof window === "undefined") return null;
    const params = new URLSearchParams(window.location.search);
    const integration = params.get("integration");
    const status = params.get("status");
    const detail = params.get("detail");

    if (integration && status) {
      const sourceName = INTEGRATION_SOURCES.find((s) => s.id === integration)?.name ?? "the integration";
      params.delete("integration");
      params.delete("status");
      params.delete("detail");
      const cleanQuery = params.toString();
      const cleanUrl = cleanQuery ? `${window.location.pathname}?${cleanQuery}` : window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);

      if (status === "connected") {
        return {
          type: "success",
          message: `Successfully connected ${sourceName}!`,
        };
      } else if (status === "error") {
        const reason = detail && ERROR_REASON_MESSAGES[detail] ? ERROR_REASON_MESSAGES[detail] : "Authorization failed.";
        return {
          type: "error",
          message: `Couldn't connect ${sourceName}: ${reason}`,
        };
      }
    }
    return null;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[#191917]">Settings</h1>
        <p className="mt-1 text-sm text-[#6E6C62] max-w-2xl leading-relaxed">
          Logline reads work signals from these sources to build your draft. Connect what you use — nothing is
          ever posted back without your approval.
        </p>
      </div>

      {callbackNotice && (
        <div
          role="alert"
          aria-live="polite"
          className={`flex items-center justify-between rounded-lg border p-3.5 font-mono text-xs ${callbackNotice.type === "success"
            ? "border-[#BFD9C2] bg-[#DCEBDD] text-[#14603C]"
            : "border-[#E0B8AC] bg-[#FBEEEA] text-[#A33A22]"
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

      {integrations.isLoading && <div className="p-8"><Loading label="Loading integrations…" /></div>}
      {integrations.isError && (
        <p className="font-mono text-xs text-[#A33A22]">Couldn&apos;t load integrations — try again.</p>
      )}

      {!integrations.isLoading && !integrations.isError && (
        <div className="space-y-4">
          <div className="flex items-baseline justify-between gap-3">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-semibold text-[#191917]">Connected sources</h2>
              <span className="font-mono text-xs text-[#8A887C]">
                {connectedCount}/{rows.length} active
              </span>
            </div>
            {attentionCount > 0 && (
              <span className="font-mono text-xs text-[#A33A22]">
                {attentionCount} need{attentionCount === 1 ? "s" : ""} attention
              </span>
            )}
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {rows.map((integration) => (
              <IntegrationCard key={integration.source} integration={integration} />
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <h2 className="text-sm font-semibold tracking-tight">Local activity</h2>
          {trackerSync.data ? (
            <TrackerSyncNotice status={trackerSync.data} />
          ) : (
            <p className="font-mono text-[11.5px] text-faint">
              {trackerSync.isError ? "Couldn't check tracker sync status." : "Checking tracker sync status…"}
            </p>
          )}
        </div>
        <TrackerDeviceEnrollment deviceCount={trackerSync.data?.device_count ?? 0} />
      </div>
    </div>
  );
}


