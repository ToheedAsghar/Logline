import { useEffect, useRef } from "react";
import { Button, type ButtonVariant } from "@/atoms";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: ButtonVariant;
  /** Disables both actions while an operation is in flight. */
  working?: boolean;
  workingLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  confirmVariant = "danger-solid",
  working = false,
  workingLabel = "Working…",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    if (dialog) {
      const focusable = dialog.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (focusable ?? dialog).focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel]);

  useEffect(() => {
    if (open) return;
    if (restoreFocusRef.current?.isConnected) {
      restoreFocusRef.current.focus();
    }
    restoreFocusRef.current = null;
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-start justify-center bg-black/40 px-4 pt-[8vh] pb-4 backdrop-blur-xs"
      onClick={onCancel}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="flex w-full max-w-[420px] flex-col rounded-xl border border-[#E3DFD2] bg-[#FFFDF7] shadow-xl"
      >
        <div className="flex items-center gap-3 border-b border-[#E3DFD2] px-5 py-4">
          <span className="font-mono text-[11px] uppercase tracking-wider text-[#8A887C]">{title}</span>
          <span className="flex-1" />
          <button
            type="button"
            aria-label="Close"
            onClick={onCancel}
            className="flex h-7 w-7 items-center justify-center rounded-md border border-[#E3DFD2] bg-[#F5F2EA] text-xs text-[#57564E] hover:bg-[#EFEBE0]"
          >
            ✕
          </button>
        </div>

        <div className="p-5">
          <p className="text-sm leading-relaxed text-[#191917]">{message}</p>

          <div className="mt-6 flex items-center justify-end gap-2.5 border-t border-[#E3DFD2] pt-5">
            <Button variant="secondary" size="md" onClick={onCancel} disabled={working}>
              {cancelLabel}
            </Button>
            <Button
              variant={confirmVariant}
              size="md"
              onClick={onConfirm}
              disabled={working}
              working={working}
              workingLabel={workingLabel}
            >
              {confirmLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
