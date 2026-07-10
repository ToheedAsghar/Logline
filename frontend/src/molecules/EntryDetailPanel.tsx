import { useEffect, useState } from "react";
import { Button, ConfidenceTier, Textarea } from "@/atoms";
import { cn, getEventEnd } from "@/common/utils";
import { useDeleteEvent, useUpdateEvent } from "@/repositories/hooks";
import type { Event } from "@/repositories/types";
import { EditableTimeField } from "./EditableTimeField";

/** Sources the backend treats as non-work time rather than a confidence level
 * — mirrors `TimelineBlock`'s `resolveTier`, kept in sync deliberately since
 * both read the same event shape (see backend CLAUDE.md). */
const NON_WORK_SOURCES = new Set(["personal", "dismissed"]);

function metadataString(metadata: Event["event_metadata"], key: string): string | undefined {
  const value = metadata?.[key];
  return typeof value === "string" ? value : undefined;
}

function fallbackTitle(type: string): string {
  return type.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Everything in `event_metadata` other than the fields already surfaced
 * elsewhere in the panel (title/summary/description/end_timestamp) — the raw,
 * read-only "Evidence" list pulled straight from the source. */
function evidenceEntries(metadata: Event["event_metadata"]): Array<{ k: string; v: string }> {
  if (!metadata) return [];
  const hidden = new Set(["title", "summary", "description", "end_timestamp"]);
  return Object.entries(metadata)
    .filter(([k]) => !hidden.has(k))
    .map(([k, v]) => ({ k: k.replace(/_/g, " "), v: typeof v === "string" ? v : JSON.stringify(v) }));
}

export interface EntryDetailPanelProps {
  event: Event;
  onClose: () => void;
}

/**
 * The entry detail slide-over (Logline.html: `selectedId`/`sel`/`hasSelected`
 * in `renderVals()`) — never built in the real app until now. Matches the
 * handoff's fields/copy: source + confidence badges, inline-editable title
 * and time range, an "estimated → confirm" action, an editable summary, the
 * raw evidence list, and a two-step delete.
 */
export function EntryDetailPanel({ event, onClose }: EntryDetailPanelProps) {
  const updateEvent = useUpdateEvent();
  const deleteEvent = useDeleteEvent();

  const title = metadataString(event.event_metadata, "title") ?? fallbackTitle(event.type);
  const summary = metadataString(event.event_metadata, "summary") ?? metadataString(event.event_metadata, "description") ?? "";
  const tier = NON_WORK_SOURCES.has(event.source) ? "personal" : event.confidence;

  const [draftTitle, setDraftTitle] = useState(title);
  const [summaryEditing, setSummaryEditing] = useState(false);
  const [draftSummary, setDraftSummary] = useState(summary);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // Re-seed local drafts whenever the selected event changes (including after
  // a save round-trips through query invalidation) — mirrors the handoff's
  // `selectEntry`/`getEv` resetting edit state per-id.
  useEffect(() => {
    setDraftTitle(title);
    setSummaryEditing(false);
    setDraftSummary(summary);
    setConfirmingDelete(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event.id]);

  const saveTitle = () => {
    if (draftTitle.trim() && draftTitle !== title) {
      updateEvent.mutate({ id: event.id, patch: { title: draftTitle } });
    } else {
      setDraftTitle(title);
    }
  };

  const startSummaryEdit = () => {
    setDraftSummary(summary);
    setSummaryEditing(true);
  };

  const cancelSummaryEdit = () => {
    setDraftSummary(summary);
    setSummaryEditing(false);
  };

  const saveSummary = () => {
    if (draftSummary !== summary) {
      updateEvent.mutate({ id: event.id, patch: { summary: draftSummary } });
    }
    setSummaryEditing(false);
  };

  const confirmEstimated = () => {
    updateEvent.mutate({ id: event.id, patch: { confidence: "proven" } });
  };

  const confirmDelete = () => {
    deleteEvent.mutate(event.id, { onSuccess: onClose });
  };

  const evidence = evidenceEntries(event.event_metadata);

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[90] flex justify-end bg-black/40"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="h-full w-[min(480px,94vw)] animate-ll-slide overflow-y-auto border-l border-border-2 bg-bg shadow-elevated"
      >
        <div className="sticky top-0 flex items-center gap-3 border-b border-border bg-bg px-5 py-4">
          <span className="rounded-xs bg-surface-2 px-[7px] py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted">
            {event.source === "note" ? "YOU" : event.source}
          </span>
          <ConfidenceTier tier={tier} shape="pill" />
          <span className="flex-1" />
          <Button variant="secondary" size="sm" iconOnly aria-label="Close" onClick={onClose} icon="✕" />
        </div>

        <div className="p-5">
          <input
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            onBlur={saveTitle}
            className="w-full border-none bg-transparent p-0.5 font-sans text-[19px] font-semibold tracking-tight text-text focus:shadow-[0_2px_0_var(--color-accent)] focus:outline-none"
          />

          <div className="mt-3">
            <EditableTimeField
              start={event.timestamp}
              end={getEventEnd(event).toISOString()}
              onConfirm={({ start, end }) =>
                updateEvent.mutate({
                  id: event.id,
                  patch: { timestamp: start, ...(end ? { end_timestamp: end } : {}) },
                })
              }
            />
          </div>

          {event.confidence === "estimated" && (
            <button
              type="button"
              onClick={confirmEstimated}
              className={cn(
                "mt-3 flex w-full items-center gap-2 rounded-md border border-accent bg-accent-soft px-3.5 py-2.5 text-left text-[13px] text-text",
                "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1",
              )}
            >
              <span className="font-semibold">This time was estimated.</span>
              <span className="flex-1" />
              <span className="font-semibold text-accent-dim">Confirm →</span>
            </button>
          )}

          <div className="mt-5">
            <div className="mb-2 flex items-center gap-2">
              <span className="font-mono text-[10.5px] uppercase tracking-wider text-accent-dim">Summary</span>
              <span className="flex-1" />
              {!summaryEditing && (
                <Button variant="secondary" size="sm" onClick={startSummaryEdit}>
                  Edit
                </Button>
              )}
            </div>
            {!summaryEditing ? (
              <div className="w-full whitespace-pre-wrap rounded-md border border-border bg-surface px-3.5 py-3 text-sm leading-relaxed text-text">
                {summary || <span className="text-faint">No summary yet.</span>}
              </div>
            ) : (
              <>
                <Textarea
                  autoFocus
                  value={draftSummary}
                  onChange={(e) => setDraftSummary(e.target.value)}
                  className="min-h-24 border-accent shadow-[0_0_0_2px_var(--color-accent-soft)]"
                />
                <div className="mt-2.5 flex items-center gap-2.5">
                  <Button variant="secondary" size="sm" onClick={cancelSummaryEdit}>
                    Cancel
                  </Button>
                  <span className="flex-1" />
                  <Button variant="primary" size="sm" onClick={saveSummary}>
                    Save summary
                  </Button>
                </div>
              </>
            )}
          </div>

          <div className="mt-5">
            <div className="mb-2.5 font-mono text-[10.5px] uppercase tracking-wider text-faint">Evidence · from source</div>
            {evidence.length === 0 ? (
              <p className="font-sans text-xs text-muted">No raw evidence for this entry.</p>
            ) : (
              <div className="flex flex-col gap-px overflow-hidden rounded-md border border-border bg-border">
                {evidence.map(({ k, v }) => (
                  <div key={k} className="flex gap-3 bg-surface px-3.5 py-2.5">
                    <span className="w-[88px] flex-none pt-px font-mono text-[11px] uppercase tracking-wide text-faint">{k}</span>
                    <span className="flex-1 break-words font-mono text-[12.5px] text-text">{v}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="mt-6 border-t border-border pt-[18px]">
            {confirmingDelete ? (
              <div className="rounded-md border border-danger bg-danger-soft px-4 py-3.5">
                <div className="mb-0.5 text-[13.5px] font-semibold">Delete this entry?</div>
                <div className="mb-3.5 text-[12.5px] leading-relaxed text-muted">
                  It&apos;ll be removed from your timeline and leave a gap for that span. This can&apos;t be undone.
                </div>
                <div className="flex gap-2.5">
                  <Button variant="secondary" size="md" className="flex-1" onClick={() => setConfirmingDelete(false)}>
                    Keep it
                  </Button>
                  <Button variant="danger-solid" size="md" className="flex-1" onClick={confirmDelete}>
                    Delete entry
                  </Button>
                </div>
              </div>
            ) : (
              <Button variant="danger" size="md" onClick={() => setConfirmingDelete(true)}>
                Delete entry
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
