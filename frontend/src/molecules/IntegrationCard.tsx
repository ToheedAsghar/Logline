import { useState, type ReactNode } from "react";
import { cn, formatRelativeTime } from "@/common/utils";
import { Button } from "@/atoms";
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
  connected: "bg-accent",
  error: "bg-danger",
  disconnected: "bg-faint",
};

const STATUS_PILL: Record<Integration["status"], string> = {
  connected: "border-accent-soft bg-accent-soft text-accent-dim",
  error: "border-danger/40 bg-danger-soft text-danger",
  disconnected: "border-border bg-transparent text-faint",
};

/**
 * Per-source icon badge colors copied verbatim from the design handoff
 * (Logline.html, `integrationCards` -> `monoStyle`) — one-off brand-ish
 * tints that stay fixed across light/dark rather than following the theme
 * palette, same as the handoff. GitHub has no fixed tint there (its mark
 * uses `var(--text)`), so it rides the theme text color instead.
 */
const DEFAULT_SOURCE_BADGE = { bg: "oklch(0.55 0.02 260 / 0.18)", color: "var(--color-text)" };

const DEFAULT_SOURCE_ICON: ReactNode = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polygon points="12 8 8 12 12 16 16 12 12 8" />
  </svg>
);

const SOURCE_BADGE: Record<string, { bg: string; color: string }> = {
  github: { bg: "oklch(0.55 0.02 260 / 0.18)", color: "var(--color-text)" },
  jira: { bg: "oklch(0.60 0.18 255 / 0.18)", color: "oklch(0.58 0.19 255)" },
  calendar: { bg: "oklch(0.62 0.18 255 / 0.18)", color: "oklch(0.60 0.18 255)" },
  slack: { bg: "oklch(0.62 0.16 330 / 0.18)", color: "oklch(0.60 0.17 330)" },
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

/** The detail line under the name — built only from fields the API actually
 * returns today (`status`, `last_synced_at`). No per-source metadata (repo
 * count, board name, channel count …) is available yet — see
 * `Integration.integration_metadata` in the backend model, which exists in
 * the DB but isn't exposed on `IntegrationResponse`. */
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

  // Catch 501 (stub) or 404 (unregistered OAuth provider e.g. calendar) as expected "not available" state.
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
        "flex flex-col rounded-xl border bg-surface p-[18px] transition-colors duration-150",
        integration.status === "error" ? "border-danger/40 hover:border-danger" : "border-border hover:border-border-2",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2.5">
        <div
          className="flex h-12 w-12 flex-none items-center justify-center rounded-lg"
          style={{ background: badge.bg, color: badge.color }}
        >
          {icon}
        </div>
        <span
          role="status"
          aria-label={`Status: ${STATUS_LABEL[integration.status]}`}
          className={cn(
            "inline-flex flex-none items-center gap-1.5 rounded-pill border px-2.5 py-1 font-mono text-[10.5px]",
            STATUS_PILL[integration.status],
          )}
        >
          <span className={cn("h-1.5 w-1.5 flex-none rounded-full", STATUS_DOT[integration.status])} />
          {STATUS_LABEL[integration.status]}
        </span>
      </div>

      <div className="mt-3.5 font-sans text-[15.5px] font-semibold tracking-tight text-text">{name}</div>
      <p className={cn("mt-1 text-[12.5px] leading-snug", integration.status === "error" ? "text-danger" : "text-muted")}>
        {detailText(integration)}
      </p>

      <div className="mt-4 flex gap-2 border-t border-border pt-3.5">
        {integration.status === "error" && (
          <Button
            variant="danger-solid"
            size="sm"
            className="flex-1"
            working={isConnecting}
            workingLabel="Reconnecting…"
            onClick={handleConnect}
          >
            Reconnect
          </Button>
        )}
        {integration.status === "disconnected" ? (
          <Button
            variant="primary"
            size="sm"
            className="flex-1"
            working={isConnecting}
            workingLabel="Connecting…"
            onClick={handleConnect}
          >
            Connect
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            className="flex-1"
            working={disconnect.isPending}
            workingLabel="Disconnecting…"
            onClick={() => disconnect.mutate(integration.source)}
          >
            Disconnect
          </Button>
        )}
      </div>

      {connectNotAvailable && (
        <p className="mt-2.5 font-mono text-[11px] text-muted">Connecting {name} isn&apos;t available yet — coming soon.</p>
      )}
      {connectFailed && <p className="mt-2.5 font-mono text-[11px] text-danger">Couldn&apos;t connect {name} — try again.</p>}
    </div>
  );
}
