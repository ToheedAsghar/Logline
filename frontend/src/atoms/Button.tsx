import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/common/utils";
import type { Size } from "@/common/types";
import { AgentCursor } from "./Loading";

export type ButtonVariant = "primary" | "secondary" | "subtle" | "ghost" | "danger" | "danger-solid";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: Size;
  iconOnly?: boolean;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
  working?: boolean;
  workingLabel?: string;
}

const BASE =
  "inline-flex items-center justify-center gap-2 font-sans font-semibold whitespace-nowrap " +
  "transition-[transform,filter,background-color,border-color,box-shadow] duration-150 ease-out " +
  "disabled:cursor-not-allowed disabled:opacity-60 " +
  "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-[#14603C] text-[#FFFDF7] border border-[#14603C] shadow-xs " +
    "enabled:hover:bg-[#0F4E31] enabled:active:translate-y-0",
  secondary:
    "bg-[#FFFDF7] text-[#191917] border border-[#CFCABA] " + "enabled:hover:bg-[#F5F2EA]",
  subtle:
    "bg-[#F5F2EA] text-[#6E6C62] border border-[#E3DFD2] " +
    "enabled:hover:bg-[#EFEBE0] enabled:hover:text-[#191917]",
  ghost: "bg-transparent text-[#6E6C62] border border-transparent " + "enabled:hover:bg-[#F5F2EA] enabled:hover:text-[#191917]",
  danger:
    "bg-transparent text-[#A33A22] border border-[#E0B8AC] " +
    "enabled:hover:bg-[#FBEEEA] enabled:hover:border-[#A33A22]",
  "danger-solid": "bg-[#A33A22] text-[#FFFDF7] border border-transparent " + "enabled:hover:bg-[#882E1A]",
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
