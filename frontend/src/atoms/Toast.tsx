import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export type ToastType = "success" | "error" | "info";

export interface ToastProps {
  message: string;
  type?: ToastType;
  onDismiss?: () => void;
}

export function Toast({ message, type = "info", onDismiss }: ToastProps) {
  return (
    <div
      className={twMerge(
        clsx(
          "pointer-events-auto relative flex w-full max-w-sm flex-col overflow-hidden rounded-md border shadow-elevated",
          "animate-[var(--animate-ll-toast)] bg-surface text-text",
          type === "error" && "border-danger/30 bg-danger-soft",
          type === "success" && "border-border-2",
          type === "info" && "border-border-2"
        )
      )}
      onClick={onDismiss}
      role="alert"
    >
      <div className="flex items-center p-4 pr-6">
        {type === "error" && (
          <svg className="mr-3 h-5 w-5 shrink-0 text-danger" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )}
        {type === "success" && (
          <svg className="mr-3 h-5 w-5 shrink-0 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        )}
        {type === "info" && (
          <svg className="mr-3 h-5 w-5 shrink-0 text-accent-dim" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )}
        <p className="text-sm font-medium">{message}</p>
      </div>
      
      <div className="h-1 w-full bg-border">
        <div 
          className={clsx(
            "h-full animate-[var(--animate-ll-toastbar)]",
            type === "error" ? "bg-danger" : "bg-accent"
          )} 
        />
      </div>
    </div>
  );
}
