import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Event } from "@/repositories/types";

/** Merge conditional class names, letting later Tailwind classes win conflicts. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** `"9:41 AM"` — the compact clock-face format events/fields render on the timeline. */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** `"9:41 AM – 11:15 AM"`, or just the start time when there's no known end. */
export function formatTimeRange(start: string, end?: string | null): string {
  return end ? `${formatTime(start)} – ${formatTime(end)}` : formatTime(start);
}

/** `"3m ago"` / `"2h ago"` / `"Never synced"` — used for integration last-sync copy. */
export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "Never synced";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * `event_metadata.end_timestamp` is only ever populated by sources that have
 * a real duration (calendar, focus blocks) — point-in-time events (a Slack
 * message, a merged PR) have none. Falling back to an assumed duration lets
 * the Timeline/GapDetector pages treat every event as occupying *some* span
 * without special-casing "does this event have an end."
 */
export function getEventEnd(event: Event, fallbackMinutes = 30): Date {
  const raw = event.event_metadata?.["end_timestamp"];
  if (typeof raw === "string") {
    const parsed = new Date(raw);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return new Date(new Date(event.timestamp).getTime() + fallbackMinutes * 60_000);
}
