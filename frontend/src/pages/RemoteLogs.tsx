import { useMemo, useState } from "react";
import { Loading } from "@/atoms";
import { cn, formatTime, htmlToPlainText } from "@/common/utils";
import { INTEGRATION_SOURCES, SOURCE_COLORS } from "@/constants";
import { ApiError } from "@/repositories/api/client";
import { useRemoteEvents, useTriggerRemoteFetch } from "@/repositories/hooks";
import type { RemoteEvent, RemoteEventListParams, RemoteEventSource } from "@/repositories/types";

const SOURCE_LABEL: Record<string, string> = {
  github: "GitHub",
  jira: "Jira",
  calendar: "Calendar",
  slack: "Slack",
};

const DEFAULT_SOURCE_COLORS = { bg: "#F5F2EA", color: "#191917" };

const DATE_INPUT =
  "appearance-none rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2.5 py-1.5 text-[#191917] font-mono text-xs focus:border-[#14603C] focus:outline-none";

function localDayKey(iso: string): string {
  const d = new Date(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function localDayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function dateToUtcBoundary(dateStr: string, daysAfter: number): string | null {
  const parts = dateStr.split("-").map(Number);
  if (parts.length < 3 || parts.some((p) => isNaN(p))) return null;
  const dt = new Date(parts[0], parts[1] - 1, parts[2] + daysAfter);
  return dt.toISOString();
}

function buildParams(filters: { source: string; startDate: string; endDate: string }): RemoteEventListParams {
  const params: RemoteEventListParams = {};
  if (filters.source !== "all") params.source = filters.source as RemoteEventSource;
  if (filters.startDate) {
    const start = dateToUtcBoundary(filters.startDate, 0);
    if (start) params.date_range_start = start;
  }
  if (filters.endDate) {
    const end = dateToUtcBoundary(filters.endDate, 1);
    if (end) params.date_range_end = end;
  }
  return params;
}

function SourceBadge({ source }: { source: string }) {
  const colors = SOURCE_COLORS[source] ?? DEFAULT_SOURCE_COLORS;
  const label = SOURCE_LABEL[source] ?? source;
  return (
    <span
      className="inline-flex items-center rounded border border-[#E3DFD2] px-2 py-0.5 text-xs font-medium"
      style={{ background: colors.bg, color: colors.color }}
    >
      {label}
    </span>
  );
}

const DESCRIPTION_DISPLAY_LIMIT = 1200;

function EventRow({ event }: { event: RemoteEvent }) {
  const [expanded, setExpanded] = useState(false);
  const [showFull, setShowFull] = useState(false);
  const hasDescription = Boolean(event.description);

  const plainDescription = expanded && event.description ? htmlToPlainText(event.description) : "";
  const isLong = plainDescription.length > DESCRIPTION_DISPLAY_LIMIT;
  const displayedDescription = isLong && !showFull ? plainDescription.slice(0, DESCRIPTION_DISPLAY_LIMIT) : plainDescription;

  return (
    <div className="p-4 hover:bg-[#FAF8F1] transition-colors">
      <div className="flex items-center gap-3">
        <SourceBadge source={event.source} />
        <span className="font-mono text-xs text-[#8A887C] min-w-14 flex-none">
          {formatTime(event.occurred_at)}
        </span>
        <p className="text-sm text-[#191917] flex-1 min-w-0 truncate leading-relaxed">
          {event.summary ?? event.event_type}
        </p>
        {hasDescription && (
          <button
            type="button"
            onClick={() => { setExpanded(!expanded); setShowFull(false); }}
            className="flex-none rounded px-2 py-1 text-xs font-medium text-[#6E6C62] hover:bg-[#F5F2EA] transition-colors"
          >
            {expanded ? "Hide" : "Details"}
          </button>
        )}
      </div>
      {expanded && event.description && (
        <div className="mt-2 ml-[76px] text-xs leading-relaxed text-[#6E6C62] whitespace-pre-wrap">
          {displayedDescription}
          {isLong && !showFull && (
            <>
              {"…"}
              <button
                type="button"
                onClick={() => setShowFull(true)}
                className="ml-1 font-medium text-[#14603C] hover:underline"
              >
                view full
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function RemoteLogs() {
  const [source, setSource] = useState<string>("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [cooldownMsg, setCooldownMsg] = useState<string | null>(null);

  const params = useMemo(() => buildParams({ source, startDate, endDate }), [source, startDate, endDate]);
  const query = useRemoteEvents(params);
  const trigger = useTriggerRemoteFetch();
  const allEvents = useMemo(() => query.data?.pages.flatMap((p) => p.events) ?? [], [query.data]);
  const hasNextPage = query.hasNextPage ?? false;

  const handleFetch = () => {
    setCooldownMsg(null);
    trigger.mutate(undefined, {
      onError: (err) => {
        if (err instanceof ApiError && err.status === 429) {
          setCooldownMsg("A fetch already ran recently. Try again in a minute.");
        } else {
          setCooldownMsg("Fetch failed — try again.");
        }
      },
    });
  };

  const grouped = useMemo(() => {
    const map = new Map<string, RemoteEvent[]>();
    for (const ev of allEvents) {
      const key = localDayKey(ev.occurred_at);
      const list = map.get(key);
      if (list) {
        list.push(ev);
      } else {
        map.set(key, [ev]);
      }
    }
    return map;
  }, [allEvents]);

  const dayKeys = useMemo(() => [...grouped.keys()], [grouped]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[#191917]">Remote Logs</h1>
        <p className="mt-1 text-sm text-[#6E6C62]">
          Activity fetched from your connected sources.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] p-3 shadow-sm">
        <div className="flex items-center gap-2">
          <label htmlFor="source-filter" className="font-mono text-[10px] tracking-wider text-[#8A887C]">
            SOURCE
          </label>
          <div className="relative">
            <select
              id="source-filter"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="appearance-none rounded-md border border-[#E3DFD2] bg-[#F5F2EA] py-1.5 pl-2.5 pr-7 font-mono text-xs font-medium text-[#191917] focus:border-[#14603C] focus:outline-none"
            >
              <option value="all">All</option>
              {INTEGRATION_SOURCES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[#57564E] text-[10px]">
              ▾
            </span>
          </div>
        </div>

        <div className="h-5 w-px bg-[#E3DFD2]" />

        <div className="flex items-center gap-2">
          <label htmlFor="start-date" className="font-mono text-[10px] tracking-wider text-[#8A887C]">
            FROM
          </label>
          <input
            id="start-date"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={DATE_INPUT}
          />
          <label htmlFor="end-date" className="font-mono text-[10px] tracking-wider text-[#8A887C]">
            TO
          </label>
          <input
            id="end-date"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className={DATE_INPUT}
          />
        </div>

        <div className="flex-1" />

        <span className="font-mono text-xs text-[#8A887C]">
          {allEvents.length} event{allEvents.length !== 1 ? "s" : ""}
        </span>

        <button
          type="button"
          onClick={handleFetch}
          disabled={trigger.isPending}
          className="rounded-md border border-[#14603C] bg-[#14603C] px-3 py-1.5 text-xs font-semibold text-[#FFFDF7] shadow-xs transition-colors hover:bg-[#0F4E31] disabled:opacity-50"
        >
          {trigger.isPending ? "Fetching…" : "Fetch now"}
        </button>
      </div>

      {cooldownMsg && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between rounded-lg border border-[#E3DFD2] bg-[#F5F2EA] p-3 font-mono text-xs text-[#8A5A0F]"
        >
          <span>{cooldownMsg}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setCooldownMsg(null)}
            className="ml-3 font-sans text-xs opacity-70 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}

      {query.isLoading && (
        <div className="p-8">
          <Loading label="Loading remote activity…" />
        </div>
      )}

      {query.isError && (
        <p className="font-mono text-xs text-[#A33A22]">
          Couldn&apos;t load remote activity — try again.
        </p>
      )}

      {!query.isLoading && !query.isError && allEvents.length === 0 && (
        <div className="rounded-lg border border-dashed border-[#CFCABA] bg-[#FFFDF7]/50 p-12 text-center">
          <span className="font-mono text-xs text-[#8A887C] uppercase block mb-2">NOTHING HERE</span>
          <p className="text-sm text-[#6E6C62]">No remote activity in this range.</p>
        </div>
      )}

      {!query.isLoading && !query.isError && allEvents.length > 0 && (
        <div className="space-y-6">
          {dayKeys.map((dayKey) => {
            const dayEvents = grouped.get(dayKey)!;
            return (
              <div key={dayKey} className="space-y-2">
                <div className="flex items-baseline gap-3 px-1">
                  <span className="font-mono text-xs font-semibold text-[#191917]">
                    {localDayLabel(dayEvents[0].occurred_at)}
                  </span>
                  <span className="font-mono text-xs text-[#8A887C]">
                    {dayEvents.length} event{dayEvents.length !== 1 ? "s" : ""}
                  </span>
                  <div className="flex-1 h-px bg-[#E3DFD2]" />
                </div>

                <div className="rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] shadow-sm divide-y divide-[#E3DFD2] overflow-hidden">
                  {dayEvents.map((ev) => (
                    <EventRow key={ev.id} event={ev} />
                  ))}
                </div>
              </div>
            );
          })}

          {hasNextPage && (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={() => query.fetchNextPage()}
                disabled={query.isFetchingNextPage}
                className={cn(
                  "rounded-md border border-[#CFCABA] bg-[#FFFDF7] px-4 py-2 text-sm font-medium text-[#191917] transition-colors hover:bg-[#F5F2EA] disabled:opacity-50",
                )}
              >
                {query.isFetchingNextPage ? "Loading more…" : "Load more"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
