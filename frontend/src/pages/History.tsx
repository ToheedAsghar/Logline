import { useState } from "react";
import { Loading } from "@/atoms";
import { escapeCsvField, formatMinutes, parseLocalDate } from "@/common/utils";
import { useEntries } from "@/repositories/hooks";

function getEntryMinutes(content: unknown): number {
  if (typeof content === "object" && content !== null) {
    const c = content as Record<string, unknown>;
    if (typeof c.manual_minutes === "number" && c.manual_minutes > 0) return c.manual_minutes;
    if (typeof c.duration_minutes === "number" && c.duration_minutes > 0) return c.duration_minutes;
    if (typeof c.minutes === "number" && c.minutes > 0) return c.minutes;
    if (Array.isArray(c.allocations) && c.allocations.length > 0) {
      const sum = c.allocations.reduce((acc: number, a: Record<string, unknown>) => acc + (Number(a?.minutes) || 0), 0);
      if (sum > 0) return sum;
    }
    if (typeof c.duration === "string") {
      const parsed = parseInt(c.duration, 10);
      if (!isNaN(parsed) && parsed > 0) return parsed;
    }
  }
  return 30;
}

function getEntryTimeDisplay(entry: { format: string; content: unknown }): string {
  if (typeof entry.content === "object" && entry.content !== null) {
    const c = entry.content as Record<string, unknown>;
    if (typeof c.duration === "string" && c.duration) return c.duration;
    if (typeof c.time === "string" && c.time) return c.time;
    if (typeof c.time_spent === "string" && c.time_spent) return c.time_spent;
    const mins = getEntryMinutes(entry.content);
    if (mins > 0) return formatMinutes(mins);
  }
  return "30m";
}

function getEntryTag(entry: { format: string; content: unknown }): string {
  if (typeof entry.content === "object" && entry.content !== null) {
    const c = entry.content as Record<string, unknown>;
    if (typeof c.tag === "string" && c.tag && c.tag !== "Other") return c.tag;
    if (typeof c.project === "string" && c.project && c.project !== "unidentified") return c.project;
  }
  if (entry.format === "standup") return "Standup";
  return "Project Log";
}

function renderEntryContent(content: unknown): React.ReactNode {
  if (typeof content === "string") return content;
  if (typeof content === "object" && content !== null) {
    const c = content as Record<string, unknown>;
    if (typeof c.text === "string") return c.text;
    if (typeof c.description === "string") return c.description;
    if (typeof c.summary === "string") return c.summary;

    if (c.yesterday || c.today || c.blockers) {
      return (
        <div className="space-y-1 text-xs">
          {Boolean(c.yesterday) && <div><span className="font-semibold text-[#191917]">Yesterday:</span> {String(c.yesterday)}</div>}
          {Boolean(c.today) && <div><span className="font-semibold text-[#191917]">Today:</span> {String(c.today)}</div>}
          {Boolean(c.blockers) && <div><span className="font-semibold text-[#8A5A0F]">Blockers:</span> {String(c.blockers)}</div>}
        </div>
      );
    }
  }
  return String(content);
}

function getWeekRange(offset: number): { start: Date; end: Date } {
  const now = new Date();
  const monday = new Date(now);
  const dayOfWeek = monday.getDay() || 7;
  monday.setDate(monday.getDate() - dayOfWeek + 1 + offset * 7);
  monday.setHours(0, 0, 0, 0);

  const sunday = new Date(monday);
  sunday.setDate(sunday.getDate() + 6);
  sunday.setHours(23, 59, 59, 999);

  return { start: monday, end: sunday };
}

function getPeriodLabel(offset: number): string {
  const { start, end } = getWeekRange(offset);
  const formatShort = (d: Date) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const rangeStr = `${formatShort(start)} - ${formatShort(end)}`;

  if (offset === 0) return `This week (${rangeStr})`;
  if (offset === -1) return `Last week (${rangeStr})`;
  if (offset < -1) return `${Math.abs(offset)} weeks ago (${rangeStr})`;
  return `Future (${rangeStr})`;
}

export default function History() {
  const [periodOffset, setPeriodOffset] = useState(0);
  const entriesQuery = useEntries({ status: "approved" });

  const { start: periodStart, end: periodEnd } = getWeekRange(periodOffset);

  const allEntries = entriesQuery.data ?? [];
  const periodEntries = allEntries.filter((entry) => {
    const entryDate = parseLocalDate(entry.work_date);
    return entryDate >= periodStart && entryDate <= periodEnd;
  });

  const groupedEntries = periodEntries.reduce<Record<string, typeof periodEntries>>((acc, entry) => {
    const dateStr = parseLocalDate(entry.work_date).toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    if (!acc[dateStr]) acc[dateStr] = [];
    acc[dateStr].push(entry);
    return acc;
  }, {});

  const exportCSV = () => {
    if (!periodEntries || periodEntries.length === 0) return;
    const headers = ["ID", "Format", "Created At", "Approved At", "Content"];
    const csvRows = periodEntries.map((e) => [
      escapeCsvField(e.id),
      escapeCsvField(e.format),
      escapeCsvField(e.created_at),
      escapeCsvField(e.approved_at || ""),
      escapeCsvField(JSON.stringify(e.content)),
    ]);
    const csvContent =
      "data:text/csv;charset=utf-8," +
      [headers.map(escapeCsvField).join(","), ...csvRows.map((r) => r.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `logline_history_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const dayKeys = Object.keys(groupedEntries);
  const totalEntriesCount = periodEntries.length;
  const totalPeriodMins = periodEntries.reduce((sum, e) => sum + getEntryMinutes(e.content), 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[#191917]">History</h1>
          <p className="mt-1 text-sm text-[#6E6C62]">
            Every saved entry, exactly as it was written to the ledger.
          </p>
        </div>

        <button
          type="button"
          onClick={exportCSV}
          disabled={totalEntriesCount === 0}
          className="rounded-md border border-[#CFCABA] bg-[#FFFDF7] px-3.5 py-2 text-sm font-medium text-[#191917] transition-colors hover:bg-[#F5F2EA] disabled:opacity-50"
        >
          Export CSV
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] shadow-sm">
        <div className="flex items-center gap-2 border-r border-[#E3DFD2] p-2">
          <button
            type="button"
            onClick={() => setPeriodOffset(periodOffset - 1)}
            aria-label="Previous period"
            className="flex h-7 w-7 items-center justify-center rounded-md text-sm text-[#57564E] transition-colors hover:bg-[#F5F2EA]"
          >
            ‹
          </button>
          <span className="font-mono text-xs font-medium text-[#191917] px-3">
            {getPeriodLabel(periodOffset)}
          </span>
          <button
            type="button"
            onClick={() => setPeriodOffset(Math.min(0, periodOffset + 1))}
            disabled={periodOffset >= 0}
            aria-label="Next period"
            className="flex h-7 w-7 items-center justify-center rounded-md text-sm text-[#57564E] transition-colors hover:bg-[#F5F2EA] disabled:opacity-30 disabled:pointer-events-none"
          >
            ›
          </button>
        </div>

        <div className="flex items-center gap-6 px-6 py-2">
          <div className="flex flex-col">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C]">TOTAL</span>
            <span className="font-mono text-sm font-medium text-[#14603C]">
              {totalPeriodMins > 0 ? formatMinutes(totalPeriodMins) : `${totalEntriesCount} entries`}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C]">DAYS</span>
            <span className="font-mono text-sm font-medium text-[#191917]">{dayKeys.length}</span>
          </div>
          <div className="flex flex-col">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C]">ENTRIES</span>
            <span className="font-mono text-sm font-medium text-[#191917]">{totalEntriesCount}</span>
          </div>
        </div>
      </div>

      {entriesQuery.isLoading && <div className="p-8"><Loading label="Loading history…" /></div>}
      {entriesQuery.isError && <p className="font-mono text-xs text-[#A33A22]">Couldn&apos;t load history ledger — try again.</p>}

      {!entriesQuery.isLoading && !entriesQuery.isError && totalEntriesCount === 0 && (
        <div className="rounded-lg border border-dashed border-[#CFCABA] bg-[#FFFDF7]/50 p-12 text-center">
          <span className="font-mono text-xs text-[#8A887C] uppercase block mb-2">NOTHING HERE</span>
          <p className="text-sm text-[#6E6C62]">No approved entries in this period ({getPeriodLabel(periodOffset)}). Reconcile and save your day to populate the ledger.</p>
        </div>
      )}

      {!entriesQuery.isLoading && !entriesQuery.isError && totalEntriesCount > 0 && (
        <div className="space-y-6">
          {dayKeys.map((dayLabel) => {
            const dayEntries = groupedEntries[dayLabel];
            const dayMins = dayEntries.reduce((sum, e) => sum + getEntryMinutes(e.content), 0);

            return (
              <div key={dayLabel} className="space-y-2">
                <div className="flex items-baseline gap-3 px-1">
                  <span className="font-mono text-xs font-semibold text-[#191917]">{dayLabel}</span>
                  <span className="font-mono text-xs text-[#8A887C]">
                    {dayMins > 0 ? `${formatMinutes(dayMins)} total` : `${dayEntries.length} entries`}
                  </span>
                  <div className="flex-1 h-px bg-[#E3DFD2]" />
                </div>

                <div className="rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] shadow-sm divide-y divide-[#E3DFD2] overflow-hidden">
                  {dayEntries.map((entry) => (
                    <div key={entry.id} className="flex items-center justify-between gap-4 p-4 hover:bg-[#FAF8F1] transition-colors">
                      <span className="font-mono text-xs font-medium text-[#191917] min-w-16 flex-none">
                        {getEntryTimeDisplay(entry)}
                      </span>
                      <div className="text-sm text-[#191917] flex-1 min-w-0 leading-relaxed">
                        {renderEntryContent(entry.content)}
                      </div>
                      <span className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2.5 py-1 text-xs font-medium text-[#57564E] flex-none">
                        {getEntryTag(entry)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
