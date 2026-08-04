import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/common/utils";
import { Button, Tooltip } from "@/atoms";
import { AccountSettingsModal } from "@/molecules";
import { SelfCaptureModal } from "@/pages/SelfCapture";

const NAV_ITEMS = [
  { to: "/", label: "Review", end: true },
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
    <div className="min-h-screen bg-[#F5F2EA] font-sans text-[#191917]">
      <header className="border-b border-[#E3DFD2] bg-[#F5F2EA] sticky top-0 z-30">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded bg-[#14603C] font-mono text-xs font-bold text-[#DCEBDD]">
              l|
            </span>
            <span className="font-mono text-base font-bold tracking-tight text-[#191917]">logline</span>
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
                    isActive
                      ? "bg-[#EFEBE0] text-[#191917] font-semibold"
                      : "text-[#6E6C62] hover:bg-[#EFEBE0] hover:text-[#191917]",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <button
            type="button"
            onClick={() => setAccountOpen(true)}
            aria-label="Account & settings"
            className="flex h-8 w-8 items-center justify-center rounded-full border border-[#CFCABA] bg-[#F1EDE2] font-mono text-xs font-semibold text-[#57564E] hover:border-[#14603C]"
          >
            TH
          </button>
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
