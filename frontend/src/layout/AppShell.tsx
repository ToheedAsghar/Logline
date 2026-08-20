import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { cn } from "@/common/utils";
import { AccountSettingsModal } from "@/molecules";

const NAV_ITEMS = [
  { to: "/", label: "Review", end: true },
  { to: "/history", label: "History" },
  { to: "/remote-logs", label: "Remote Logs" },
  { to: "/settings", label: "Settings" },
];

export function AppShell() {
  const [accountOpen, setAccountOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[#F5F2EA] font-sans text-[#191917]">
      <header className="border-b border-[#E3DFD2] bg-[#F5F2EA] sticky top-0 z-30">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3">
          <Link to="/" className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity">
            <span className="flex h-6 w-6 items-center justify-center rounded bg-[#14603C] font-mono text-xs font-bold text-[#DCEBDD]">
              l|
            </span>
            <span className="font-mono text-base font-bold tracking-tight text-[#191917]">logline</span>
          </Link>

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

      <AccountSettingsModal open={accountOpen} onClose={() => setAccountOpen(false)} />
    </div>
  );
}
