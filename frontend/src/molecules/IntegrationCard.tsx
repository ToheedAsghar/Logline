import { cn, formatRelativeTime } from "@/common/utils";
import { Button } from "@/atoms";
import { INTEGRATION_SOURCES } from "@/constants/integrations";
import { ApiError } from "@/repositories/api/client";
import { useConnectIntegration, useDisconnectIntegration } from "@/repositories/hooks";
import type { Integration } from "@/repositories/types";

const STATUS_DOT: Record<Integration["status"], string> = {
  connected: "bg-accent",
  disconnected: "bg-faint",
  error: "bg-danger",
};

const STATUS_LABEL: Record<Integration["status"], string> = {
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Error",
};

export interface IntegrationCardProps {
  integration: Integration;
  className?: string;
}

export function IntegrationCard({ integration, className }: IntegrationCardProps) {
  const connect = useConnectIntegration();
  const disconnect = useDisconnectIntegration();

  const name = INTEGRATION_SOURCES.find((s) => s.id === integration.source)?.name ?? integration.source;

  // The backend's connect endpoint is a permanent 501 stub today (see
  // backend/app/api/integrations.py) — that's an expected, calm "not yet
  // available" state, not a crash or a red error banner.
  const connectNotAvailable = connect.isError && connect.error instanceof ApiError && connect.error.status === 501;
  const connectFailed = connect.isError && !connectNotAvailable;

  return (
    <div className={cn("flex flex-col gap-2 rounded-md border border-border-2 bg-surface px-4 py-3", className)}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className={cn("h-2 w-2 flex-none rounded-full", STATUS_DOT[integration.status])} />
          <div>
            <div className="font-sans text-sm font-medium text-text">{name}</div>
            <div className="font-mono text-[11px] text-faint">
              {STATUS_LABEL[integration.status]} · {formatRelativeTime(integration.last_synced_at)}
            </div>
          </div>
        </div>

        {integration.status === "connected" ? (
          <Button
            variant="danger"
            size="sm"
            working={disconnect.isPending}
            workingLabel="Disconnecting…"
            onClick={() => disconnect.mutate(integration.source)}
          >
            Disconnect
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            working={connect.isPending}
            workingLabel="Connecting…"
            onClick={() => connect.mutate(integration.source)}
          >
            Connect
          </Button>
        )}
      </div>

      {connectNotAvailable && (
        <p className="font-mono text-[11px] text-faint">Connecting {name} isn&apos;t available yet — coming soon.</p>
      )}
      {connectFailed && <p className="font-mono text-[11px] text-danger">Couldn&apos;t connect {name} — try again.</p>}
    </div>
  );
}
