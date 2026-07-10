import { cn, formatTimeRange } from "@/common/utils";
import { ConfidenceTier } from "@/atoms";
import { CONFIDENCE_TIERS, type ConfidenceTier as Tier } from "@/constants/tokens";
import type { Event } from "@/repositories/types";

/** Sources the backend treats as non-work time rather than a confidence level
 * (see backend `CLAUDE.md`: "non-work time is not a special confidence value
 * — it's `source='personal'`/`source='dismissed'` with `confidence='proven'`").
 * TimelineBlock is the one place that distinction gets folded back into the
 * `ConfidenceTier` vocabulary for display. */
const NON_WORK_SOURCES = new Set(["personal", "dismissed"]);

function resolveTier(event: Event): Tier {
  return NON_WORK_SOURCES.has(event.source) ? "personal" : event.confidence;
}

/** `event_metadata` is arbitrary per-source JSON (see backend `CLAUDE.md`'s
 * generic event shape) — pull display strings out of it defensively rather
 * than assuming any particular integration's field names. */
function metadataString(metadata: Event["event_metadata"], key: string): string | undefined {
  const value = metadata?.[key];
  return typeof value === "string" ? value : undefined;
}

function fallbackTitle(type: string): string {
  return type.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface TimelineBlockProps {
  event: Event;
  /** Opens the entry detail panel (`EntryDetailPanel`) for this event. */
  onSelect?: (event: Event) => void;
  className?: string;
}

export function TimelineBlock({ event, onSelect, className }: TimelineBlockProps) {
  const tier = resolveTier(event);
  const cfg = CONFIDENCE_TIERS[tier];
  const title = metadataString(event.event_metadata, "title") ?? fallbackTitle(event.type);
  const summary = metadataString(event.event_metadata, "summary") ?? metadataString(event.event_metadata, "description");
  const endTimestamp = metadataString(event.event_metadata, "end_timestamp");

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onSelect?.(event)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect?.(event);
        }
      }}
      className={cn(
        "flex flex-col gap-1.5 rounded-md border-[1.5px] bg-surface px-3.5 py-3 text-left",
        "cursor-pointer transition-colors hover:bg-surface-2",
        "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
        cfg.borderStyle === "solid" && "border-solid",
        cfg.borderStyle === "dashed" && "border-dashed",
        cfg.borderStyle === "dotted" && "border-dotted",
        "border-border-2",
        cfg.hasLeftAccent && (tier === "proven" ? "border-l-[3px] border-l-accent" : "border-l-[3px] border-l-accent-dim"),
        className,
      )}
      style={{ opacity: cfg.opacity }}
    >
      <div className="flex items-center gap-2">
        <ConfidenceTier tier={tier} shape="dot" />
        <span className="font-mono text-[11px] text-faint">{formatTimeRange(event.timestamp, endTimestamp)}</span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-faint">{event.source}</span>
      </div>
      <h3 className="font-sans text-sm font-medium text-text">{title}</h3>
      {summary && <p className="line-clamp-2 font-sans text-xs text-muted">{summary}</p>}
    </article>
  );
}
