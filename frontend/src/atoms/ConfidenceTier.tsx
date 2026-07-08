import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/common/utils";
import { CONFIDENCE_TIERS, type ConfidenceTier as Tier } from "@/constants/tokens";

/**
 * The confidence-tier visual language: every fact Logline shows is either
 * `proven` (solid, evidence-backed), `estimated` (softer, dashed, still
 * editable), a `gap` (empty outline — an open question), or `personal`
 * (hatched — time away, not counted as work). This single primitive renders
 * that vocabulary consistently so pages/molecules never hand-roll borders.
 *
 * Three shapes cover every place the handoff uses this system:
 *  - `swatch`  — the small rectangle used in the auth-screen legend
 *  - `dot`     — the compact indicator used on timeline block headers
 *  - `pill`    — the labeled badge used in the entry detail slide-over
 */
export type ConfidenceTierShape = "swatch" | "dot" | "pill";

export interface ConfidenceTierProps extends HTMLAttributes<HTMLSpanElement> {
  tier: Tier;
  shape?: ConfidenceTierShape;
  /** Pill only: override the label (defaults to the tier's display name). */
  label?: ReactNode;
}

const BORDER_STYLE: Record<Tier, string> = {
  proven: "border-solid",
  estimated: "border-dashed",
  gap: "border-dotted",
  personal: "border-solid",
};

function Swatch({ tier, className, ...props }: Omit<ConfidenceTierProps, "shape">) {
  const cfg = CONFIDENCE_TIERS[tier];
  return (
    <span
      className={cn(
        "inline-block w-[34px] h-4 flex-none rounded-xs border-[1.5px]",
        BORDER_STYLE[tier],
        "border-muted",
        cfg.hasLeftAccent && (tier === "proven" ? "border-l-[3px] border-l-accent" : "border-l-[3px] border-l-accent-dim"),
        tier === "personal" &&
          "bg-[repeating-linear-gradient(135deg,transparent,transparent_6px,var(--color-surface-2)_6px,var(--color-surface-2)_12px)]",
        className,
      )}
      style={{ opacity: cfg.opacity }}
      {...props}
    />
  );
}

function Dot({ tier, className, ...props }: Omit<ConfidenceTierProps, "shape">) {
  const cfg = CONFIDENCE_TIERS[tier];
  return (
    <span
      className={cn(
        "inline-block w-[7px] h-[7px] rounded-full flex-none",
        cfg.dot === "solid-accent" && "bg-accent",
        cfg.dot === "dashed-accent" && "border-[1.5px] border-dashed border-accent-dim",
        cfg.dot === "solid-faint" && "bg-faint",
        className,
      )}
      {...props}
    />
  );
}

function Pill({ tier, label, className, ...props }: Omit<ConfidenceTierProps, "shape">) {
  const cfg = CONFIDENCE_TIERS[tier];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm px-2.5 py-0.5 font-mono text-[11px]",
        tier === "proven" && "bg-accent-soft text-accent-dim",
        tier === "estimated" && "border border-dashed border-border-2 text-muted",
        (tier === "gap" || tier === "personal") && "border border-dotted border-border-2 text-faint",
        className,
      )}
      {...props}
    >
      {label ?? cfg.label}
    </span>
  );
}

export function ConfidenceTier({ shape = "dot", ...props }: ConfidenceTierProps) {
  if (shape === "swatch") return <Swatch {...props} />;
  if (shape === "pill") return <Pill {...props} />;
  return <Dot {...props} />;
}
