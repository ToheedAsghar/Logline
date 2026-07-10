import { useMemo, useState } from "react";
import { cn, getEventEnd } from "@/common/utils";
import { Loading } from "@/atoms";
import { EntryDetailPanel, RefreshTimelineTrigger, TimelineBlock } from "@/molecules";
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

/** Vertical, time-proportional column for a single day: each event is
 * positioned/sized by its actual timestamp span rather than listed flatly,
 * so the empty stretches between events read as visual gaps. */
function DayColumn({ date, events, onSelect }: { date: Date; events: Event[]; onSelect: (event: Event) => void }) {
  const dayStart = atHour(date, DISPLAY_DAY_START_HOUR);
  const totalMinutes = (DISPLAY_DAY_END_HOUR - DISPLAY_DAY_START_HOUR) * 60;
  const hours = Array.from(
    { length: DISPLAY_DAY_END_HOUR - DISPLAY_DAY_START_HOUR + 1 },
    (_, i) => DISPLAY_DAY_START_HOUR + i,
  );

  const positioned = useMemo(
    () =>
      events.map((event) => {
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
      }),
    [events, dayStart, totalMinutes],
  );

  return (
    <div className="relative flex" style={{ height: totalMinutes * PIXELS_PER_MINUTE }}>
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
        {positioned.map(({ event, top, height }) => (
          <div key={event.id} className="absolute inset-x-2" style={{ top, height }}>
            <TimelineBlock event={event} onSelect={onSelect} className="h-full" />
          </div>
        ))}
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
        <DayColumn date={anchorDate} events={sortedEvents} onSelect={(event) => setSelectedEventId(event.id)} />
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
