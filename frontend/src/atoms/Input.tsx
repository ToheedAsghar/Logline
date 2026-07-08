import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/common/utils";

/**
 * Shared visual treatment for text fields (see e.g. the auth email/password
 * fields, capture message box, entry-detail title field in the handoff):
 * flat bg, 1px border, 9px radius. On focus the border goes transparent and
 * a 2px accent outline takes over, so there's never a doubled border+ring.
 */
const FIELD_BASE =
  "w-full bg-bg border border-border rounded-md px-[13px] py-[11px] " +
  "font-sans text-sm text-text placeholder:text-faint " +
  "outline-none focus:border-transparent focus:outline focus:outline-2 focus:outline-accent focus:outline-offset-1 " +
  "disabled:opacity-60 disabled:cursor-not-allowed";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(FIELD_BASE, className)} {...props} />;
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
