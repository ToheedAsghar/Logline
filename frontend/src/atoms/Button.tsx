import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/common/utils";
import type { Size } from "@/common/types";
import { AgentCursor } from "./Loading";

export type ButtonVariant = "primary" | "secondary" | "subtle" | "ghost" | "danger" | "danger-solid";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: Size;
  /** Renders as a square icon-only button (close ✕, settings gear, calendar nav …). */
  iconOnly?: boolean;
  /** Leading icon/element (SVG glyph). */
  icon?: ReactNode;
  /** Trailing icon/element — e.g. the chevron on "Generate standup". */
  trailingIcon?: ReactNode;
  /**
   * The Logline "agent working" state — checking tools / correlating
   * signals. Deliberately not a generic spinner: swaps the button's content
   * for the brand blink-cursor + status copy (matching the handoff's
   * `refreshWorkingStyle` pill) and disables interaction. See `Loading.tsx`.
   */
  working?: boolean;
  workingLabel?: string;
}

const BASE =
  "inline-flex items-center justify-center gap-2 font-sans font-semibold whitespace-nowrap " +
  "transition-[transform,filter,background-color,border-color,box-shadow] duration-150 ease-out " +
  "disabled:cursor-not-allowed disabled:opacity-60 " +
  "outline-none focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-ink border border-transparent shadow-[0_4px_14px_var(--color-accent-soft)] " +
    "enabled:hover:brightness-[1.06] enabled:hover:-translate-y-px enabled:active:translate-y-0",
  secondary:
    "bg-transparent text-text border border-border-2 " + "enabled:hover:bg-surface-2 enabled:hover:border-text",
  subtle:
    "bg-surface-2 text-muted border border-border-2 " +
    "enabled:hover:bg-surface enabled:hover:border-accent enabled:hover:text-text",
  ghost: "bg-transparent text-muted border border-transparent " + "enabled:hover:bg-surface-2 enabled:hover:text-text",
  danger:
    "bg-transparent text-danger border border-border " +
    "enabled:hover:bg-danger-soft enabled:hover:border-danger",
  "danger-solid": "bg-danger text-bg border border-transparent " + "enabled:hover:brightness-[1.06]",
};

const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-xs rounded-sm gap-1.5",
  md: "h-[42px] px-4 text-[13.5px] rounded-md gap-2",
  lg: "h-12 px-5 text-[15px] rounded-lg gap-2.5",
};

const ICON_ONLY_SIZE: Record<Size, string> = {
  sm: "h-7 w-7 rounded-sm p-0",
  md: "h-[30px] w-[30px] rounded-sm p-0",
  lg: "h-9 w-9 rounded-md p-0",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    iconOnly = false,
    icon,
    trailingIcon,
    working = false,
    workingLabel = "Working…",
    disabled,
    className,
    children,
    ...props
  },
  ref,
) {
  if (working) {
    return (
      <span
        role="status"
        aria-live="polite"
        className={cn(
          BASE,
          "bg-surface border border-accent text-text cursor-default",
          iconOnly ? ICON_ONLY_SIZE[size] : SIZE[size],
          className,
        )}
      >
        <AgentCursor size={size} />
        {!iconOnly && <span className="font-mono text-[11.5px] font-medium">{workingLabel}</span>}
      </span>
    );
  }

  return (
    <button
      ref={ref}
      disabled={disabled}
      className={cn(BASE, VARIANT[variant], iconOnly ? ICON_ONLY_SIZE[size] : SIZE[size], className)}
      {...props}
    >
      {icon}
      {!iconOnly && children}
      {trailingIcon}
    </button>
  );
});
