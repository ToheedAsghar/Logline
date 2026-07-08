import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/common/utils";

export type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> & {
  label?: string;
};

/**
 * Not present in the handoff (it has no checkbox control anywhere — toggles
 * are done as buttons, e.g. integration connect/disconnect). Built net-new
 * for the requested atom, reusing the handoff's tokens and its one
 * recurring checkmark glyph (`M5 13l4 4 10-11`, the same path used for
 * "Approve", the toast success icon, and the per-source "done" mark) so it
 * reads as part of the same system rather than a generic browser checkbox.
 */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, className, id, disabled, ...props },
  ref,
) {
  return (
    <label
      htmlFor={id}
      className={cn(
        "inline-flex items-center gap-2.5 font-sans text-sm text-text select-none",
        disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer",
        className,
      )}
    >
      <span className="relative inline-flex h-[18px] w-[18px] flex-none">
        <input
          ref={ref}
          id={id}
          type="checkbox"
          disabled={disabled}
          className="peer absolute inset-0 h-full w-full cursor-pointer appearance-none rounded-xs border border-border-2 bg-bg outline-none transition-colors checked:border-accent checked:bg-accent focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 disabled:cursor-not-allowed"
          {...props}
        />
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={3}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="pointer-events-none absolute inset-0 m-auto h-3 w-3 scale-0 text-accent-ink transition-transform peer-checked:scale-100 peer-checked:animate-ll-pop"
        >
          <path d="M5 13l4 4 10-11" />
        </svg>
      </span>
      {label ? <span>{label}</span> : null}
    </label>
  );
});
