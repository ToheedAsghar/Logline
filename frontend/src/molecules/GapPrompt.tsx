import { useState, type FormEvent } from "react";
import { cn, formatTimeRange } from "@/common/utils";
import { Button, ConfidenceTier, Input } from "@/atoms";
import { useCreateSelfCapture } from "@/repositories/hooks";

export interface GapPromptProps {
  /** ISO start/end of the unaccounted range (as computed by the backend's
   * `flag_gap`, which never persists a row — gaps have no id of their own). */
  start: string;
  end: string;
  /** Set only if a future gap-numbering scheme exists to link back to. */
  linkedGapId?: number;
  onCaptured?: () => void;
  className?: string;
}

/**
 * A gap is an open question, never an error — the design brief is explicit
 * that gaps must not read as red/alarm state. Visual weight comes from the
 * `gap` ConfidenceTier tier (dotted outline) rather than any danger styling.
 */
export function GapPrompt({ start, end, linkedGapId, onCaptured, className }: GapPromptProps) {
  const [text, setText] = useState("");
  const createSelfCapture = useCreateSelfCapture();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    createSelfCapture.mutate(
      { text: trimmed, timestamp: start, linked_gap_id: linkedGapId ?? null },
      {
        onSuccess: () => {
          setText("");
          onCaptured?.();
        },
      },
    );
  };

  return (
    <div
      className={cn(
        "flex flex-col gap-2.5 rounded-md border-[1.5px] border-dotted border-border-2 bg-surface px-3.5 py-3",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <ConfidenceTier tier="gap" shape="dot" />
        <span className="font-mono text-[11px] text-faint">{formatTimeRange(start, end)}</span>
        <span className="font-sans text-sm text-muted">What were you doing here?</span>
      </div>
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Debugging the deploy pipeline"
          disabled={createSelfCapture.isPending}
          className="flex-1"
        />
        <Button type="submit" variant="secondary" size="sm" disabled={!text.trim() || createSelfCapture.isPending}>
          Save
        </Button>
      </form>
      {createSelfCapture.isError && (
        <p className="font-mono text-[11px] text-faint">Couldn&apos;t save that — try again.</p>
      )}
    </div>
  );
}
