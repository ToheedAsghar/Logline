import { useState, type ReactNode } from "react";
import { cn, formatRelativeTime } from "@/common/utils";
import { INTEGRATION_SOURCES } from "@/constants/integrations";
import { ApiError } from "@/repositories/api/client";
import { useConnectIntegration, useDisconnectIntegration } from "@/repositories/hooks";
import type { Integration } from "@/repositories/types";

const STATUS_LABEL: Record<Integration["status"], string> = {
  connected: "Connected",
  error: "Attention",
  disconnected: "Disconnected",
};

const STATUS_DOT: Record<Integration["status"], string> = {
  connected: "bg-[#14603C]",
  error: "bg-[#A33A22]",
  disconnected: "bg-[#8A887C]",
};

const STATUS_PILL: Record<Integration["status"], string> = {
  connected: "border-[#BFD9C2] bg-[#DCEBDD] text-[#14603C]",
  error: "border-[#E0B8AC] bg-[#FBEEEA] text-[#A33A22]",
  disconnected: "border-[#E3DFD2] bg-[#F5F2EA] text-[#8A887C]",
};

const DEFAULT_SOURCE_BADGE = { bg: "#F5F2EA", color: "#191917" };

const DEFAULT_SOURCE_ICON: ReactNode = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polygon points="12 8 8 12 12 16 16 12 12 8" />
  </svg>
);

const SOURCE_BADGE: Record<string, { bg: string; color: string }> = {
  github: { bg: "#F5F2EA", color: "#191917" },
  jira: { bg: "#EBF3FB", color: "#0052CC" },
  calendar: { bg: "#EBF3FB", color: "#1A73E8" },
  slack: { bg: "#FBEBF3", color: "#4A154B" },
};

const SOURCE_ICON: Record<string, ReactNode> = {
  github: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.09.68-.22.68-.49l-.01-1.9c-2.78.62-3.37-1.2-3.37-1.2-.46-1.18-1.11-1.5-1.11-1.5-.9-.63.07-.62.07-.62 1 .07 1.53 1.05 1.53 1.05.89 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.37-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.7 0 0 .84-.28 2.75 1.05a9.36 9.36 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.4.2 2.44.1 2.7.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.81-4.57 5.06.36.32.68.94.68 1.9l-.01 2.81c0 .27.18.59.69.49A10.26 10.26 0 0 0 22 12.25C22 6.58 17.52 2 12 2z" />
    </svg>
  ),
  jira: (
    <svg width="21" height="21" viewBox="0 0 24 24" fill="currentColor">
      <path d="M11.53 2c0 2.4 1.97 4.35 4.35 4.35h1.78v1.7c0 2.4 1.94 4.34 4.34 4.35V2.84a.84.84 0 0 0-.84-.84zM6.77 6.8a4.362 4.362 0 0 0 4.34 4.34h1.8v1.72a4.362 4.362 0 0 0 4.34 4.34V7.63a.83.83 0 0 0-.83-.83zM2 11.6c0 2.4 1.95 4.34 4.35 4.34h1.78v1.72c.01 2.39 1.95 4.33 4.34 4.34v-9.57a.84.84 0 0 0-.83-.83z" />
    </svg>
  ),
  calendar: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4.5" width="18" height="17" rx="2.5" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="8" y1="2.5" x2="8" y2="6" />
      <line x1="16" y1="2.5" x2="16" y2="6" />
    </svg>
  ),
  slack: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
      <path d="M6 15a2 2 0 1 1-2-2h2v2zm1 0a2 2 0 0 1 4 0v5a2 2 0 1 1-4 0v-5z" />
      <path d="M9 6a2 2 0 1 1 2-2v2H9zm0 1a2 2 0 0 1 0 4H4a2 2 0 1 1 0-4h5z" />
      <path d="M18 9a2 2 0 1 1 2 2h-2V9zm-1 0a2 2 0 0 1-4 0V4a2 2 0 1 1 4 0v5z" />
      <path d="M15 18a2 2 0 1 1-2 2v-2h2zm0-1a2 2 0 0 1 0-4h5a2 2 0 1 1 0 4h-5z" />
    </svg>
  ),
};

function detailText(integration: Integration): string {
  if (integration.status === "connected") return `Synced ${formatRelativeTime(integration.last_synced_at)}`;
  if (integration.status === "error") return "Needs attention — reconnect to resume syncing.";
  return "Not connected yet.";
}

export interface IntegrationCardProps {
  integration: Integration;
  className?: string;
}

export function IntegrationCard({ integration, className }: IntegrationCardProps) {
  const connect = useConnectIntegration();
  const disconnect = useDisconnectIntegration();
  const [isRedirecting, setIsRedirecting] = useState(false);

  const name = INTEGRATION_SOURCES.find((s) => s.id === integration.source)?.name ?? integration.source;
  const badge = SOURCE_BADGE[integration.source] ?? DEFAULT_SOURCE_BADGE;
  const icon = SOURCE_ICON[integration.source] ?? DEFAULT_SOURCE_ICON;

  const connectNotAvailable =
    connect.isError &&
    connect.error instanceof ApiError &&
    (connect.error.status === 501 || connect.error.status === 404);
  const connectFailed = connect.isError && !connectNotAvailable;

  const isConnecting = (connect.isPending || isRedirecting) && !connectFailed && !connectNotAvailable;

  const handleConnect = () => {
    setIsRedirecting(true);
    connect.mutate(integration.source, {
      onError: () => setIsRedirecting(false),
    });
  };

  return (
    <div
      className={cn(
        "flex flex-col rounded-xl border bg-[#FFFDF7] p-5 shadow-xs transition-all duration-150",
        integration.status === "error" ? "border-[#E0B8AC] hover:border-[#A33A22]" : "border-[#E3DFD2] hover:border-[#CFCABA]",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2.5">
        <div
          className="flex h-11 w-11 flex-none items-center justify-center rounded-lg border border-[#E3DFD2]"
          style={{ background: badge.bg, color: badge.color }}
        >
          {icon}
        </div>
        <span
          role="status"
          aria-label={`Status: ${STATUS_LABEL[integration.status]}`}
          className={cn(
            "inline-flex flex-none items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10.5px] font-medium",
            STATUS_PILL[integration.status],
          )}
        >
          <span className={cn("h-1.5 w-1.5 flex-none rounded-full", STATUS_DOT[integration.status])} />
          {STATUS_LABEL[integration.status]}
        </span>
      </div>

      <div className="mt-4 font-sans text-base font-semibold tracking-tight text-[#191917]">{name}</div>
      <p className={cn("mt-1 text-xs leading-relaxed", integration.status === "error" ? "text-[#A33A22]" : "text-[#6E6C62]")}>
        {detailText(integration)}
      </p>

      <div className="mt-5 flex gap-2 border-t border-[#E3DFD2] pt-4">
        {integration.status === "error" && (
          <button
            type="button"
            disabled={isConnecting}
            onClick={handleConnect}
            className="flex-1 rounded-md border border-[#E0B8AC] bg-[#FBEEEA] py-2 text-xs font-semibold text-[#A33A22] hover:bg-[#F7DDD6] disabled:opacity-50"
          >
            {isConnecting ? "Reconnecting…" : "Reconnect"}
          </button>
        )}
        {integration.status === "disconnected" ? (
          <button
            type="button"
            disabled={isConnecting}
            onClick={handleConnect}
            className="flex-1 rounded-md border border-[#14603C] bg-[#14603C] py-2 text-xs font-semibold text-[#FFFDF7] shadow-xs hover:bg-[#0F4E31] disabled:opacity-50"
          >
            {isConnecting ? "Connecting…" : "Connect"}
          </button>
        ) : (
          <button
            type="button"
            disabled={disconnect.isPending}
            onClick={() => disconnect.mutate(integration.source)}
            className="flex-1 rounded-md border border-[#E3DFD2] bg-[#F5F2EA] py-2 text-xs font-medium text-[#191917] hover:bg-[#EFEBE0] disabled:opacity-50"
          >
            {disconnect.isPending ? "Disconnecting…" : "Disconnect"}
          </button>
        )}
      </div>

      {connectNotAvailable && (
        <p className="mt-2.5 font-mono text-[11px] text-[#8A887C]">Connecting {name} isn&apos;t available yet — coming soon.</p>
      )}
      {connectFailed && <p className="mt-2.5 font-mono text-[11px] text-[#A33A22]">Couldn&apos;t connect {name} — try again.</p>}
    </div>
  );
}
