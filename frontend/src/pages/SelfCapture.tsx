import { useEffect, useState, type FormEvent } from "react";
import { Button, Textarea } from "@/atoms";
import { useCreateSelfCapture } from "@/repositories/hooks";

export interface SelfCaptureModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Quick-entry capture, reachable from the persistent FAB (see
 * `layout/AppShell.tsx`) on every authenticated page — not tied to a
 * specific gap, so `linked_gap_id` is omitted and `timestamp` is just "now."
 * Shares `useCreateSelfCapture()` with `GapPrompt`; the only difference is
 * this one isn't anchored to a known time range.
 */
export function SelfCaptureModal({ open, onClose }: SelfCaptureModalProps) {
  const [text, setText] = useState("");
  const createSelfCapture = useCreateSelfCapture();

  useEffect(() => {
    if (!open) {
      setText("");
      createSelfCapture.reset();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    createSelfCapture.mutate(
      { text: trimmed, timestamp: new Date().toISOString(), linked_gap_id: null },
      { onSuccess: onClose },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 px-4 pb-24 sm:items-center sm:pb-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Quick capture"
        onClick={(e) => e.stopPropagation()}
        className="flex w-full max-w-md flex-col gap-3 rounded-lg border border-border-2 bg-surface p-5 shadow-elevated"
      >
        <div>
          <h2 className="font-sans text-base font-semibold text-text">Quick capture</h2>
          <p className="mt-0.5 font-sans text-sm text-muted">Jot down what you&apos;re doing — we&apos;ll fold it in later.</p>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <Textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Pairing with Sam on the payments bug"
            rows={3}
            disabled={createSelfCapture.isPending}
          />
          {createSelfCapture.isError && (
            <p className="font-mono text-[11px] text-danger">Couldn&apos;t save that — try again.</p>
          )}
          <div className="flex items-center justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={!text.trim() || createSelfCapture.isPending}
              working={createSelfCapture.isPending}
              workingLabel="Saving…"
            >
              Save
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
