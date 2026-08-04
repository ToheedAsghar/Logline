import type { ReactNode } from "react";
import { cn } from "@/common/utils";
import { Button, ConfidenceTier } from "@/atoms";
import { CONFIDENCE_TIERS, type ConfidenceTier as Tier } from "@/constants/tokens";
import { getGoogleLoginUrl } from "@/repositories/api/auth";

function GithubIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.09.68-.22.68-.49l-.01-1.9c-2.78.62-3.37-1.2-3.37-1.2-.46-1.18-1.11-1.5-1.11-1.5-.9-.63.07-.62.07-.62 1 .07 1.53 1.05 1.53 1.05.89 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.37-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.7 0 0 .84-.28 2.75 1.05a9.36 9.36 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.4.2 2.44.1 2.7.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.81-4.57 5.06.36.32.68.94.68 1.9l-.01 2.81c0 .27.18.59.69.49A10.26 10.26 0 0 0 22 12.25C22 6.58 17.52 2 12 2z" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.76c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.09a6.6 6.6 0 0 1 0-4.18V7.07H2.18a11 11 0 0 0 0 9.86l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
    </svg>
  );
}

const LEGEND_TIERS: Tier[] = ["proven", "estimated", "gap"];

/** One row of the auth-screen confidence-tier legend — reuses `ConfidenceTier`'s
 * `swatch` shape for the border treatment rather than re-implementing it, only
 * overriding the swatch border color to the panel's (always-dark) sidebar tokens. */
function LegendRow({ tier }: { tier: Tier }) {
  const cfg = CONFIDENCE_TIERS[tier];
  return (
    <div className="flex items-center gap-[11px]">
      <ConfidenceTier
        tier={tier}
        shape="swatch"
        className={cn("border-sidebar-muted", tier === "proven" && "bg-white/5")}
      />
      <span className="text-[13px] text-sidebar-muted">
        <span className="font-medium text-sidebar-text">{cfg.label}</span> — {cfg.description}
      </span>
    </div>
  );
}

/** Uppercase micro-label above each auth text field (Name/Work email/Password). */
export function AuthFieldLabel({ children }: { children: ReactNode }) {
  return (
    <label className="mt-[13px] mb-1.5 block font-mono text-[10.5px] tracking-[0.06em] text-faint uppercase">
      {children}
    </label>
  );
}

interface AuthShellProps {
  title: string;
  subtitle: string;
  onGoogleClick?: () => void;
  hideDivider?: boolean;
  children: ReactNode;
}

/**
 * Split-screen chrome shared by Login/Signup/Password Auth screens.
 */
export function AuthShell({ title, subtitle, onGoogleClick, hideDivider = false, children }: AuthShellProps) {
  const handleGoogleClick = () => {
    if (onGoogleClick) {
      onGoogleClick();
    } else {
      window.location.href = getGoogleLoginUrl();
    }
  };

  return (
    <div className="flex min-h-screen bg-bg font-sans text-text">
      <div className="hidden w-[42%] max-w-[460px] flex-none flex-col gap-[18px] border-r border-sidebar-border bg-sidebar-bg px-[42px] py-11 min-[820px]:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex h-[38px] w-[38px] flex-none items-center justify-center gap-px rounded-[11px] bg-accent">
            <span className="font-mono text-[19px] font-bold tracking-[-0.04em] text-accent-ink">l</span>
            <span className="h-4 w-[5px] rounded-[1px] bg-accent-ink animate-ll-blink" />
          </span>
          <span className="font-mono text-xl font-semibold tracking-[-0.02em] text-sidebar-text">logline</span>
        </div>

        <div className="my-auto">
          <h2 className="m-0 text-[29px] font-semibold leading-[1.2] tracking-[-0.02em] text-sidebar-text">
            Your work, logged
            <br />
            before you forget it.
          </h2>
          <p className="mt-4 max-w-[38ch] text-[14.5px] leading-[1.6] text-sidebar-muted">
            Logline reads your GitHub, calendar, tickets and chat, correlates them into a daily timeline, and drafts
            your standup — you just approve.
          </p>
          <div className="mt-7 flex flex-col gap-[11px]">
            {LEGEND_TIERS.map((tier) => (
              <LegendRow key={tier} tier={tier} />
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-1 items-center justify-center px-6 py-8">
        <div className="w-full max-w-[380px] animate-ll-rise">
          <div className="mb-[22px] flex items-center gap-2.5 min-[820px]:hidden">
            <span className="font-mono text-[21px] font-semibold tracking-[-0.02em]">logline</span>
            <span className="h-[19px] w-[9px] rounded-[1px] bg-accent animate-ll-blink" />
          </div>

          <h1 className="m-0 text-[23px] font-semibold tracking-[-0.02em]">{title}</h1>
          <p className="mt-2 mb-[22px] text-[13.5px] leading-[1.5] text-muted">{subtitle}</p>

          {!hideDivider && (
            <>
              <div className="flex flex-col gap-[9px]">
                <Button type="button" variant="secondary" className="w-full" icon={<GithubIcon />}>
                  Continue with GitHub
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  className="w-full"
                  icon={<GoogleIcon />}
                  onClick={handleGoogleClick}
                >
                  Continue with Google
                </Button>
              </div>

              <div className="my-[18px] flex items-center gap-3">
                <span className="h-px flex-1 bg-border" />
                <span className="font-mono text-[10.5px] text-faint">or with email</span>
                <span className="h-px flex-1 bg-border" />
              </div>
            </>
          )}

          {children}
        </div>
      </div>
    </div>
  );
}
