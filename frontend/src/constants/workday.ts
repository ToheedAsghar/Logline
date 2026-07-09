import type { DateRange } from "@/repositories/types";

/**
 * Two separate day windows, deliberately distinct:
 *  - DISPLAY: the range the Timeline page scales itself against — generous,
 *    since off-hours events (a late PR, a weekend commit) still need somewhere
 *    to render.
 *  - WORK_COVERAGE: the narrower range GapDetector checks for uncovered time —
 *    only the hours a user is actually expected to be logging work.
 */
export const DISPLAY_DAY_START_HOUR = 6;
export const DISPLAY_DAY_END_HOUR = 22;

export const WORK_COVERAGE_START_HOUR = 9;
export const WORK_COVERAGE_END_HOUR = 18;

/** Below this, a silent stretch reads as "between events," not a gap worth prompting for. */
export const MIN_GAP_MINUTES = 20;

export function atHour(date: Date, hour: number): Date {
  const d = new Date(date);
  d.setHours(hour, 0, 0, 0);
  return d;
}

export function dayDisplayRange(date: Date): DateRange {
  return { start: atHour(date, DISPLAY_DAY_START_HOUR).toISOString(), end: atHour(date, DISPLAY_DAY_END_HOUR).toISOString() };
}

export function workCoverageRange(date: Date): DateRange {
  return { start: atHour(date, WORK_COVERAGE_START_HOUR).toISOString(), end: atHour(date, WORK_COVERAGE_END_HOUR).toISOString() };
}

/** The Monday of `date`'s week, at 00:00. */
export function startOfWeek(date: Date): Date {
  const day = date.getDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  const monday = new Date(date);
  monday.setDate(date.getDate() + mondayOffset);
  monday.setHours(0, 0, 0, 0);
  return monday;
}

/** Monday–Sunday of `date`'s week, full calendar days. */
export function weekRange(date: Date): DateRange {
  const monday = startOfWeek(date);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  sunday.setHours(23, 59, 59, 999);
  return { start: monday.toISOString(), end: sunday.toISOString() };
}

export function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
