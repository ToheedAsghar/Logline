import { useState } from "react";
import { cn, formatTimeRange } from "@/common/utils";

export interface EditableTimeFieldProps {
  start: string;
  end?: string | null;
  onConfirm: (next: { start: string; end?: string | null }) => void;
  className?: string;
}

/** `Date` → local `HH:MM` for a native `<input type="time">`. */
function toTimeInputValue(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Re-applies an edited `HH:MM` onto the original date, keeping the day/tz
 * of `original` intact — this field only ever edits time-of-day. */
function withTime(original: string, hhmm: string): string {
  const [hours, minutes] = hhmm.split(":").map(Number);
  const d = new Date(original);
  d.setHours(hours, minutes, 0, 0);
  return d.toISOString();
}

/**
 * Inline-editable time range. Renders as plain text until clicked, then swaps
 * to native time inputs; confirming or cancelling only ever touches this
 * field's own local draft state, so editing one field can't clobber sibling
 * fields on the same entry/event.
 */
export function EditableTimeField({ start, end, onConfirm, className }: EditableTimeFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draftStart, setDraftStart] = useState(() => toTimeInputValue(start));
  const [draftEnd, setDraftEnd] = useState(() => (end ? toTimeInputValue(end) : ""));

  const beginEditing = () => {
    // Re-seed the draft from current props only at the moment editing starts,
    // so unrelated re-renders while *not* editing never disturb an in-progress edit.
    setDraftStart(toTimeInputValue(start));
    setDraftEnd(end ? toTimeInputValue(end) : "");
    setEditing(true);
  };

  const cancel = () => setEditing(false);

  const confirm = () => {
    onConfirm({
      start: withTime(start, draftStart),
      end: draftEnd ? withTime(end ?? start, draftEnd) : null,
    });
    setEditing(false);
  };

  if (!editing) {
    return (
      <button
        type="button"
        onClick={beginEditing}
        className={cn(
          "rounded-sm px-1.5 py-0.5 font-mono text-[11px] text-faint transition-colors",
          "hover:bg-surface-2 hover:text-text outline-none focus-visible:outline-2 focus-visible:outline-accent",
          className,
        )}
      >
        {formatTimeRange(start, end)}
      </button>
    );
  }

  return (
    <span className={cn("inline-flex items-center gap-1.5 font-mono text-[11px]", className)}>
      <input
        type="time"
        value={draftStart}
        onChange={(e) => setDraftStart(e.target.value)}
        className="rounded-xs border border-border bg-bg px-1 py-0.5 text-text outline-none focus:border-transparent focus:outline focus:outline-2 focus:outline-accent"
      />
      <span className="text-faint">–</span>
      <input
        type="time"
        value={draftEnd}
        onChange={(e) => setDraftEnd(e.target.value)}
        className="rounded-xs border border-border bg-bg px-1 py-0.5 text-text outline-none focus:border-transparent focus:outline focus:outline-2 focus:outline-accent"
      />
      <button
        type="button"
        onClick={confirm}
        aria-label="Confirm time"
        className="rounded-xs px-1 text-accent-dim hover:bg-accent-soft"
      >
        ✓
      </button>
      <button
        type="button"
        onClick={cancel}
        aria-label="Cancel edit"
        className="rounded-xs px-1 text-faint hover:bg-surface-2"
      >
        ✕
      </button>
    </span>
  );
}
