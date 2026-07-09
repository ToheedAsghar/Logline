import { useMemo, useState } from "react";
import { Loading } from "@/atoms";
import { GapPrompt } from "@/molecules";
import { useTimeline } from "@/repositories/hooks";
import { MIN_GAP_MINUTES, WORK_COVERAGE_END_HOUR, WORK_COVERAGE_START_HOUR, workCoverageRange } from "@/constants/workday";
import { getEventEnd } from "@/common/utils";
import type { Event } from "@/repositories/types";

interface GapRange {
  key: string;
  start: string;
  end: string;
}

/**
 * Derives uncovered stretches of the work day from raw events.
 *
 * There's no backend "gaps" endpoint to call here (see the GapDetector doc
 * comment below for why) — this reimplements just enough of what the
 * backend's `flag_gap` tool checks (is any event present in a range) to
 * additionally *enumerate* every uncovered range in a day, which `flag_gap`
 * itself doesn't do: it only answers yes/no for a single range the caller
 * already picked.
 */
function computeGaps(events: Event[], rangeStart: Date, rangeEnd: Date): GapRange[] {
  const intervals = events
    .map((event) => {
      const start = new Date(event.timestamp);
      const end = getEventEnd(event);
      return [start.getTime(), Math.max(end.getTime(), start.getTime())] as const;
    })
    .sort((a, b) => a[0] - b[0]);

  const merged: Array<[number, number]> = [];
  for (const [start, end] of intervals) {
    const clampedStart = Math.max(start, rangeStart.getTime());
    const clampedEnd = Math.min(end, rangeEnd.getTime());
    if (clampedEnd <= rangeStart.getTime() || clampedStart >= rangeEnd.getTime()) continue;
    const last = merged[merged.length - 1];
    if (last && clampedStart <= last[1]) {
      last[1] = Math.max(last[1], clampedEnd);
    } else {
      merged.push([clampedStart, clampedEnd]);
    }
  }

  const gaps: GapRange[] = [];
  let cursor = rangeStart.getTime();
  const minGapMs = MIN_GAP_MINUTES * 60_000;
  for (const [start, end] of merged) {
    if (start - cursor >= minGapMs) {
      gaps.push({ key: `${cursor}-${start}`, start: new Date(cursor).toISOString(), end: new Date(start).toISOString() });
    }
    cursor = Math.max(cursor, end);
  }
  if (rangeEnd.getTime() - cursor >= minGapMs) {
    gaps.push({ key: `${cursor}-${rangeEnd.getTime()}`, start: new Date(cursor).toISOString(), end: rangeEnd.toISOString() });
  }
  return gaps;
}

export default function GapDetector() {
  const [selectedDate] = useState(() => new Date());

  const dateRange = workCoverageRange(selectedDate);
  const timeline = useTimeline(dateRange);

  // A self-capture now writes a real Event row server-side (see
  // useCreateSelfCapture), so a filled gap genuinely disappears once the
  // timeline query above refetches -- no client-side/session-only hiding
  // needed here anymore.
  const gaps = useMemo(() => {
    if (!timeline.data) return [];
    const start = new Date(dateRange.start);
    const end = new Date(dateRange.end);
    return computeGaps(timeline.data, start, end);
  }, [timeline.data, dateRange.start, dateRange.end]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Gaps</h1>
        <p className="text-sm text-muted">
          Uncovered stretches between {WORK_COVERAGE_START_HOUR}:00 and {WORK_COVERAGE_END_HOUR}:00 today — worth a
          quick note, not a red flag.
        </p>
      </div>

      {timeline.isLoading && <Loading label="Checking your timeline…" />}
      {timeline.isError && <p className="font-mono text-[11px] text-danger">Couldn&apos;t load today&apos;s timeline — try again.</p>}

      {!timeline.isLoading && !timeline.isError && gaps.length === 0 && (
        <div className="flex flex-col items-start gap-1 rounded-md border border-border bg-surface px-4 py-6">
          <p className="font-sans text-sm font-medium text-text">Nothing to flag.</p>
          <p className="font-sans text-sm text-muted">Your day looks fully accounted for so far.</p>
        </div>
      )}

      {!timeline.isLoading && !timeline.isError && gaps.length > 0 && (
        <div className="flex flex-col gap-3">
          {gaps.map((gap) => (
            <GapPrompt key={gap.key} start={gap.start} end={gap.end} />
          ))}
        </div>
      )}
    </div>
  );
}
