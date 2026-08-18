import type { HTMLAttributes } from "react";
import { cn } from "@/common/utils";
import type { Size } from "@/common/types";

/**
 * Logline's brand "thinking" motif — a blinking cursor bar, the same shape
 * as the dash in the sidebar wordmark / logo mark (see the handoff's
 * `.ll-wordmark` cursor and the `l|` logo glyph). Deliberately NOT a
 * spinner: the brief calls for something distinct per the product's
 * identity, and this is the one motif the handoff reuses everywhere the
 * app is "loading" — the review page's draft generation, history/settings
 * fetches, and the FAB/auth logo.
 */
const CURSOR_SIZES: Record<Size, string> = {
  sm: "w-[4px] h-[11px]",
  md: "w-[5px] h-[14px]",
  lg: "w-[7px] h-[18px]",
};

export function AgentCursor({
  size = "md",
  className,
}: {
  size?: Size;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block flex-none rounded-[1px] bg-accent animate-ll-blink",
        CURSOR_SIZES[size],
        className,
      )}
    />
  );
}

/** The sequential 3-dot pulse used per-source while the agent reads each
 * integration (see `showDots` rows in the Compose "working" state). Tone
 * follows the row's outcome: accent-dim while progressing, danger while
 * retrying an errored source. */
export function AgentWorkingDots({
  tone = "accent",
  className,
}: {
  tone?: "accent" | "danger";
  className?: string;
}) {
  const dotColor = tone === "danger" ? "bg-danger" : "bg-accent-dim";
  return (
    <span className={cn("inline-flex items-center gap-[3px]", className)} aria-hidden="true">
      {[0, 0.16, 0.32].map((delay) => (
        <span
          key={delay}
          className={cn("w-1 h-1 rounded-full animate-ll-dots", dotColor)}
          style={{ animationDelay: `${delay}s` }}
        />
      ))}
    </span>
  );
}

export interface LoadingProps extends HTMLAttributes<HTMLSpanElement> {
  /** Status copy, e.g. "Checking your tools…" / "Working…". */
  label?: string;
  size?: Size;
}

/**
 * General-purpose "the agent is working" indicator. Use this — not a
 * spinner — anywhere Logline is doing agent work (checking tools,
 * correlating signals). `Button`'s `working` prop renders this internally;
 * use `Loading` directly for standalone status rows/pills.
 */
export function Loading({ label = "Working…", size = "md", className, ...props }: LoadingProps) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center gap-2 font-mono text-faint", className)}
      {...props}
    >
      <AgentCursor size={size} />
      <span className={label ? undefined : "sr-only"}>{label || "Loading"}</span>
    </span>
  );
}
