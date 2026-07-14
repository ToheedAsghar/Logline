import { useEffect, useMemo, useState } from "react";
import { cn, formatTimeRange, getEventEnd } from "@/common/utils";
import { Loading } from "@/atoms";
import { EntryDetailPanel, RefreshTimelineTrigger, TimelineBlock, TimelineClusterRow } from "@/molecules";
import { useTimeline } from "@/repositories/hooks";
import {
  DISPLAY_DAY_END_HOUR,
  DISPLAY_DAY_START_HOUR,
  atHour,
  dayDisplayRange,
  isSameDay,
  startOfWeek,
  weekRange,
} from "@/constants/workday";
import type { Event } from "@/repositories/types";

type ViewMode = "day" | "week";

/** 1px/minute over the display window (16h → 960px) — dense enough to read
 * gaps between events at a glance without needing to scroll a full 24h. */
const PIXELS_PER_MINUTE = 1;
const MIN_BLOCK_PX = 44;
const HOUR_COLUMN_WIDTH = 44;

/** Cluster-row layout, ported from the timeline-overlap spec (1a): once 2+
 * events collide, height stops encoding duration for the cluster's members —
 * they collapse into slim, fixed-height rows and the time-range label carries
 * duration instead. Single (non-colliding) events are unaffected. */
const ROW_H = 34;
const ROW_GAP = 5;
const CLUSTER_HEAD = 20;
const CLUSTER_INDENT = 12;
const UNIT_GAP = 6;
const MIN_CLUSTER = 2;

/** Canonical order + display labels for the source filter (1a's sibling
 * feature, 1d). Only these are ever offered as filter chips — anything else
 * a source happens to be (e.g. an internal "system" gap marker) still dims
 * like normal but never gets its own chip. */
const CANONICAL_SOURCES = ["github", "calendar", "jira", "slack", "personal", "note"] as const;
const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  calendar: "Calendar",
  jira: "Jira",
  slack: "Slack",
  personal: "Personal",
  note: "Note",
};

function addDays(date: Date, days: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}

function formatDayLabel(date: Date, opts: Intl.DateTimeFormatOptions = { weekday: "long", month: "short", day: "numeric" }): string {
  return date.toLocaleDateString(undefined, opts);
}

function formatHourLabel(hour: number): string {
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve}${hour < 12 ? "am" : "pm"}`;
}

interface NaturalUnit {
  event: Event;
  top: number;
  height: number;
}

/** Each event's true time-proportional position, before any collision
 * handling — identical to the position it would render at alone. */
function naturalUnits(events: Event[], dayStart: Date, totalMinutes: number): NaturalUnit[] {
  return events.map((event) => {
    const start = new Date(event.timestamp);
    const end = getEventEnd(event);
    const startMin = Math.min(Math.max((start.getTime() - dayStart.getTime()) / 60_000, 0), totalMinutes);
    const endMinRaw = (end.getTime() - dayStart.getTime()) / 60_000;
    const endMin = Math.min(Math.max(endMinRaw, startMin), totalMinutes);
    return {
      event,
      top: startMin * PIXELS_PER_MINUTE,
      height: Math.max((endMin - startMin) * PIXELS_PER_MINUTE, MIN_BLOCK_PX),
    };
  });
}

interface UnitGroup {
  units: NaturalUnit[];
  /** A `gap`-confidence unit never merges with anything, in either direction
   * — it stays its own group even if it visually overlaps a real event. */
  isGap: boolean;
}

/** Interval sweep: walks units in start order and folds a run of colliding
 * *events* (never gaps) into one group. This also incidentally fixes the
 * "gap card renders on top of a real event" overlap, since a gap is now
 * always placed as its own unit by the cursor pass below rather than
 * absolutely-positioned independently of its neighbors.
 *
 * Known limitation: a gap sitting between two time-overlapping real events
 * breaks the run — the event after the gap starts a fresh group instead of
 * joining the cluster before it, even though it does overlap that cluster.
 * The y-cursor placement below still prevents any visual overlap, so this
 * never produces illegible cards, it just under-clusters that one case
 * (renders as separate single cards rather than one bracketed group). Not
 * fixed here — flagging for whoever revisits this. */
function sweepGroups(units: NaturalUnit[]): UnitGroup[] {
  const sorted = [...units].sort((a, b) => a.top - b.top || b.height - a.height);
  const groups: UnitGroup[] = [];
  let curBottom = -Infinity;
  for (const unit of sorted) {
    const isGap = unit.event.confidence === "gap";
    const bottom = unit.top + unit.height;
    const cur = groups[groups.length - 1];
    if (cur && !cur.isGap && !isGap && unit.top < curBottom + UNIT_GAP) {
      cur.units.push(unit);
      curBottom = Math.max(curBottom, bottom);
    } else {
      groups.push({ units: [unit], isGap });
      curBottom = bottom;
    }
  }
  return groups;
}

export type PositionedUnit =
  | { kind: "single"; event: Event; top: number; height: number }
  | { kind: "cluster"; events: Event[]; top: number; height: number };

/** y-cursor placement: each group keeps its natural top position unless a
 * preceding group would overlap it, in which case it's nudged down just
 * enough. Hour gridlines stay at true time behind the cards. */
function placeGroups(groups: UnitGroup[]): { units: PositionedUnit[]; cursor: number } {
  let cursor = 0;
  const units: PositionedUnit[] = [];
  for (const group of groups) {
    const top = Math.max(group.units[0].top, cursor);
    const isCluster = group.units.length >= MIN_CLUSTER;
    const height = isCluster
      ? CLUSTER_HEAD + group.units.length * ROW_H + (group.units.length - 1) * ROW_GAP
      : group.units[0].height;
    units.push(
      isCluster
        ? { kind: "cluster", events: group.units.map((u) => u.event), top, height }
        : { kind: "single", event: group.units[0].event, top, height },
    );
    cursor = top + height + UNIT_GAP;
  }
  return { units, cursor };
}

export function layoutDayEvents(
  events: Event[],
  dayStart: Date,
  totalMinutes: number,
): { units: PositionedUnit[]; trackHeight: number } {
  const { units, cursor } = placeGroups(sweepGroups(naturalUnits(events, dayStart, totalMinutes)));
  return { units, trackHeight: Math.max(totalMinutes * PIXELS_PER_MINUTE, cursor) };
}

/** A gap is inherently sourceless (an open question, not tied to one
 * integration) — it dims under any active filter regardless of what its
 * nominal `source` happens to be. */
export function isDimmedBySourceFilter(event: Event, srcFilter: string): boolean {
  return srcFilter !== "all" && (event.confidence === "gap" || event.source !== srcFilter);
}

/** Sources present that day, restricted to the filter's fixed vocabulary and
 * ordered per the spec's canonical order — used both to decide which chips
 * to show and whether to show the row at all (≥2 required). */
function filterableSources(events: Event[]): string[] {
  const present = new Set(events.map((e) => e.source));
  return CANONICAL_SOURCES.filter((s) => present.has(s));
}

function SourceFilterRow({ sources, active, onPick }: { sources: string[]; active: string; onPick: (s: string) => void }) {
  const chips: Array<{ key: string; label: string }> = [{ key: "all", label: "All" }, ...sources.map((s) => ({ key: s, label: SOURCE_LABELS[s] ?? s }))];
  return (
    <div className="mb-3.5 flex flex-wrap gap-1.5">
      {chips.map((chip) => {
        const isActive = active === chip.key;
        return (
          <button
            key={chip.key}
            type="button"
            onClick={() => onPick(isActive ? "all" : chip.key)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-[11px] py-1 font-sans text-[11px]",
              isActive ? "border-accent bg-accent-soft font-semibold text-accent" : "border-border-2 bg-transparent text-muted",
            )}
          >
            {isActive && <span className="h-[5px] w-[5px] flex-none rounded-full bg-accent" />}
            {chip.label}
          </button>
        );
      })}
    </div>
  );
}

/** Vertical, time-proportional column for a single day: each event is
 * positioned/sized by its actual timestamp span rather than listed flatly,
 * so the empty stretches between events read as visual gaps. Colliding
 * events (2+ overlapping in time) collapse into a bracketed cluster of slim
 * rows instead of overlapping each other (spec 1a). */
function DayColumn({
  date,
  events,
  onSelect,
  srcFilter,
}: {
  date: Date;
  events: Event[];
  onSelect: (event: Event) => void;
  srcFilter: string;
}) {
  const dayStart = atHour(date, DISPLAY_DAY_START_HOUR);
  const totalMinutes = (DISPLAY_DAY_END_HOUR - DISPLAY_DAY_START_HOUR) * 60;
  const hours = Array.from(
    { length: DISPLAY_DAY_END_HOUR - DISPLAY_DAY_START_HOUR + 1 },
    (_, i) => DISPLAY_DAY_START_HOUR + i,
  );

  const { units, trackHeight } = useMemo(
    () => layoutDayEvents(events, dayStart, totalMinutes),
    [events, dayStart, totalMinutes],
  );

  return (
    <div className="relative flex" style={{ height: trackHeight }}>
      <div className="relative flex-none" style={{ width: HOUR_COLUMN_WIDTH }}>
        {hours.map((hour) => (
          <div
            key={hour}
            className="absolute left-0 -translate-y-1/2 font-mono text-[10px] text-faint"
            style={{ top: (hour - DISPLAY_DAY_START_HOUR) * 60 * PIXELS_PER_MINUTE }}
          >
            {formatHourLabel(hour)}
          </div>
        ))}
      </div>
      <div className="relative flex-1 border-l border-border">
        {hours.map((hour) => (
          <div
            key={hour}
            className="absolute inset-x-0 border-t border-border"
            style={{ top: (hour - DISPLAY_DAY_START_HOUR) * 60 * PIXELS_PER_MINUTE }}
          />
        ))}
        {units.map((unit) => {
          if (unit.kind === "single") {
            return (
              <div key={unit.event.id} className="absolute inset-x-2" style={{ top: unit.top, height: unit.height }}>
                <TimelineBlock
                  event={unit.event}
                  onSelect={onSelect}
                  className="h-full"
                  dimmed={isDimmedBySourceFilter(unit.event, srcFilter)}
                />
              </div>
            );
          }

          const matchCount = srcFilter === "all" ? -1 : unit.events.filter((e) => e.source === srcFilter).length;
          const groupDimmed = srcFilter !== "all" && matchCount === 0;
          const headerLabel = matchCount > 0 ? `${matchCount} ${srcFilter} events` : `${unit.events.length} close events`;
          const minStart = unit.events.reduce((min, e) => (new Date(e.timestamp) < new Date(min.timestamp) ? e : min));
          const maxEnd = unit.events.reduce((max, e) => (getEventEnd(e) > getEventEnd(max) ? e : max));

          return (
            <div key={`cluster-${unit.events[0].id}`} className="absolute inset-x-2" style={{ top: unit.top, height: unit.height }}>
              <div
                className="h-full border-l-2 border-border-2"
                style={{ paddingLeft: CLUSTER_INDENT, opacity: groupDimmed ? 0.32 : 1, transition: "opacity 150ms ease" }}
                aria-hidden={groupDimmed || undefined}
              >
                <div className="flex items-center justify-between" style={{ height: CLUSTER_HEAD }}>
                  <span className="font-mono text-[9.5px] uppercase tracking-wider text-faint">{headerLabel}</span>
                  <span className="font-mono text-[10px] text-faint">
                    {formatTimeRange(minStart.timestamp, getEventEnd(maxEnd).toISOString())}
                  </span>
                </div>
                <div className="flex flex-col" style={{ gap: ROW_GAP }}>
                  {unit.events.map((event) => (
                    <TimelineClusterRow
                      key={event.id}
                      event={event}
                      onSelect={onSelect}
                      dimmed={!groupDimmed && isDimmedBySourceFilter(event, srcFilter)}
                    />
                  ))}
                </div>
              </div>
            </div>
          );
        })}
        {events.length === 0 && (
          <p className="absolute inset-x-2 top-6 font-sans text-sm text-muted">Nothing logged yet — Refresh Timeline to check your tools.</p>
        )}
      </div>
    </div>
  );
}

export default function Timeline() {
  const [viewMode, setViewMode] = useState<ViewMode>("day");
  const [anchorDate, setAnchorDate] = useState(() => new Date());
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [srcFilter, setSrcFilter] = useState<string>("all");

  const dateRange = viewMode === "day" ? dayDisplayRange(anchorDate) : weekRange(anchorDate);
  const timeline = useTimeline(dateRange);

  const sortedEvents = useMemo(
    () => [...(timeline.data ?? [])].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()),
    [timeline.data],
  );

  const selectedEvent = sortedEvents.find((event) => event.id === selectedEventId) ?? null;

  const weekDays = useMemo(() => {
    const monday = startOfWeek(anchorDate);
    return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  }, [anchorDate]);

  // Manual, view-only filter state — never persisted, and must never leak
  // across days or between day/week view.
  useEffect(() => {
    setSrcFilter("all");
  }, [anchorDate, viewMode]);

  const daySources = useMemo(() => (viewMode === "day" ? filterableSources(sortedEvents) : []), [sortedEvents, viewMode]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Timeline</h1>
          <p className="text-sm text-muted">
            {viewMode === "day" ? formatDayLabel(anchorDate) : `Week of ${formatDayLabel(weekDays[0], { month: "short", day: "numeric" })}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex gap-1 rounded-lg border border-border bg-surface p-1">
            <button
              onClick={() => setViewMode("day")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-semibold",
                viewMode === "day" ? "bg-accent text-accent-ink" : "text-muted",
              )}
            >
              Day
            </button>
            <button
              onClick={() => setViewMode("week")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-semibold",
                viewMode === "week" ? "bg-accent text-accent-ink" : "text-muted",
              )}
            >
              Week
            </button>
          </div>
          {viewMode === "day" && (
            <div className="flex items-center gap-1">
              <button
                onClick={() => setAnchorDate((d) => addDays(d, -1))}
                aria-label="Previous day"
                className="rounded-md border border-border-2 px-2 py-1.5 text-xs text-muted hover:bg-surface-2"
              >
                ←
              </button>
              <button
                onClick={() => setAnchorDate(new Date())}
                className="rounded-md border border-border-2 px-2.5 py-1.5 text-xs text-muted hover:bg-surface-2"
              >
                Today
              </button>
              <button
                onClick={() => setAnchorDate((d) => addDays(d, 1))}
                aria-label="Next day"
                className="rounded-md border border-border-2 px-2 py-1.5 text-xs text-muted hover:bg-surface-2"
              >
                →
              </button>
            </div>
          )}
          <RefreshTimelineTrigger />
        </div>
      </div>

      {timeline.isLoading && <Loading label="Loading timeline…" />}
      {timeline.isError && <p className="font-mono text-[11px] text-danger">Couldn&apos;t load the timeline — try again.</p>}

      {!timeline.isLoading && !timeline.isError && viewMode === "day" && (
        <>
          {daySources.length >= 2 && <SourceFilterRow sources={daySources} active={srcFilter} onPick={setSrcFilter} />}
          <DayColumn date={anchorDate} events={sortedEvents} onSelect={(event) => setSelectedEventId(event.id)} srcFilter={srcFilter} />
        </>
      )}

      {!timeline.isLoading && !timeline.isError && viewMode === "week" && (
        <div className="flex flex-col gap-5">
          {weekDays.map((day) => {
            const dayEvents = sortedEvents.filter((event) => isSameDay(new Date(event.timestamp), day));
            return (
              <section key={day.toDateString()} className="flex flex-col gap-2.5">
                <h2 className="font-mono text-[11px] uppercase tracking-wider text-faint">{formatDayLabel(day)}</h2>
                {dayEvents.length === 0 ? (
                  <p className="font-sans text-sm text-muted">Nothing logged.</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {dayEvents.map((event) => (
                      <TimelineBlock key={event.id} event={event} onSelect={(e) => setSelectedEventId(e.id)} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {selectedEvent && <EntryDetailPanel event={selectedEvent} onClose={() => setSelectedEventId(null)} />}
    </div>
  );
}
