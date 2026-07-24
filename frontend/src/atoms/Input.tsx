import { forwardRef, useState, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/common/utils";

function EyeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
      <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
      <path d="M6.61 6.61A13.52 13.52 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
      <line x1="2" x2="22" y1="2" y2="22" />
    </svg>
  );
}

/**
 * Shared visual treatment for text fields (see e.g. the auth email/password
 * fields, capture message box, entry-detail title field in the handoff):
 * flat bg, 1px border, 9px radius. On focus the border goes transparent and
 * a 2px accent outline takes over, so there's never a doubled border+ring.
 */
const FIELD_BASE =
  "w-full bg-bg border border-border rounded-md px-[13px] py-[11px] " +
  "font-sans text-sm text-text placeholder:text-faint " +
  "focus:border-transparent focus:outline focus:outline-2 focus:outline-accent focus:outline-offset-1 " +
  "disabled:opacity-60 disabled:cursor-not-allowed";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  showPasswordToggle?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, type, showPasswordToggle = true, ...props },
  ref,
) {
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const isPasswordType = type === "password";

  if (isPasswordType && showPasswordToggle) {
    const inputType = isPasswordVisible ? "text" : "password";
    return (
      <div className="relative w-full">
        <input
          ref={ref}
          type={inputType}
          className={cn(FIELD_BASE, "pr-10", className)}
          {...props}
        />
        <button
          type="button"
          onClick={() => setIsPasswordVisible(!isPasswordVisible)}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-faint hover:text-muted focus:outline-none focus:text-text transition-colors"
          title={isPasswordVisible ? "Hide password" : "Show password"}
          aria-label={isPasswordVisible ? "Hide password" : "Show password"}
        >
          {isPasswordVisible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </div>
    );
  }

  return <input ref={ref} type={type} className={cn(FIELD_BASE, className)} {...props} />;
});

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

/** Same field treatment, resizable — used for compose drafts, capture notes,
 * entry summaries. */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, ...props },
  ref,
) {
  return <textarea ref={ref} className={cn(FIELD_BASE, "resize-y leading-relaxed", className)} {...props} />;
});
