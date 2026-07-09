import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/common/utils";
import { Button, Tooltip } from "@/atoms";
import { AccountSettingsModal } from "@/molecules";
import { SelfCaptureModal } from "@/pages/SelfCapture";

const NAV_ITEMS = [
  { to: "/", label: "Timeline", end: true },
  { to: "/gaps", label: "Gaps" },
  { to: "/compose", label: "Compose" },
  { to: "/history", label: "History" },
  { to: "/settings", label: "Settings" },
];

/** Any element that should keep taking its own keystrokes over the global "c" shortcut. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
}

/**
 * Top-level app shell for every authenticated page: nav bar + the persistent
 * quick-capture FAB (design handoff's "Quick capture (C)" affordance — see
 * Phase 1's Tooltip on the styleguide page). Mounted once by the router, so
 * `SelfCaptureModal`'s open state survives navigation between pages.
 */
export function AppShell() {
  const [captureOpen, setCaptureOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "c" && !e.metaKey && !e.ctrlKey && !e.altKey && !isTypingTarget(e.target)) {
        setCaptureOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="min-h-screen bg-bg font-sans text-text">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center gap-px rounded-md bg-accent">
              <span className="font-mono text-sm font-bold text-accent-ink">l</span>
              <span className="h-3.5 w-1 rounded-[1px] bg-accent-ink animate-ll-blink" />
            </span>
            <span className="font-mono text-base font-semibold">logline</span>
          </div>

          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 font-sans text-sm font-medium transition-colors",
                    isActive ? "bg-accent-soft text-accent-dim" : "text-muted hover:bg-surface-2 hover:text-text",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <Tooltip content="Account & settings" side="bottom">
            <Button
              variant="secondary"
              iconOnly
              size="sm"
              aria-label="Account & settings"
              className="rounded-full"
              onClick={() => setAccountOpen(true)}
              icon={
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              }
            />
          </Tooltip>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>

      <div className="fixed bottom-6 right-6 z-40">
        <Tooltip content="Quick capture (C)" side="left">
          <Button
            variant="primary"
            iconOnly
            size="lg"
            aria-label="Quick capture"
            className="rounded-full shadow-elevated"
            onClick={() => setCaptureOpen(true)}
            icon={<span className="text-xl leading-none">+</span>}
          />
        </Tooltip>
      </div>

      <SelfCaptureModal open={captureOpen} onClose={() => setCaptureOpen(false)} />
      <AccountSettingsModal open={accountOpen} onClose={() => setAccountOpen(false)} />
    </div>
  );
}
