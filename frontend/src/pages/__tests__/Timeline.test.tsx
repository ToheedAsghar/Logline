import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Timeline, { layoutDayEvents, isDimmedBySourceFilter } from "../Timeline";
import type { Event } from "@/repositories/types";

vi.mock("@/repositories/hooks", () => ({
  useTimeline: vi.fn(),
  useRunAgent: vi.fn(),
}));

import { useTimeline, useRunAgent } from "@/repositories/hooks";

let nextId = 1;
const mockEvent = (overrides: Partial<Event>): Event => ({
  id: nextId++,
  type: "test_event",
  source: "github",
  confidence: "proven",
  timestamp: "2024-01-01T10:00:00",
  created_at: "2024-01-01T10:00:00Z",
  event_metadata: { title: "Untitled" },
  ...overrides,
});

/** ISO timestamp for "today" at a given local hour/minute, so events land
 * inside the day view's actual display window regardless of when the test
 * suite runs. */
function todayAt(hour: number, minute = 0): string {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

describe("layoutDayEvents", () => {
  const dayStart = new Date("2024-01-01T06:00:00");
  const totalMinutes = (22 - 6) * 60;

  it("keeps a single, non-colliding event at its natural position, untouched", () => {
    const event = mockEvent({ timestamp: "2024-01-01T09:00:00" });
    const { units } = layoutDayEvents([event], dayStart, totalMinutes);
    expect(units).toHaveLength(1);
    expect(units[0].kind).toBe("single");
  });

  it("does not cluster two events that don't visually overlap", () => {
    const a = mockEvent({ timestamp: "2024-01-01T09:00:00" });
    const b = mockEvent({ timestamp: "2024-01-01T11:00:00" });
    const { units } = layoutDayEvents([a, b], dayStart, totalMinutes);
    expect(units).toHaveLength(2);
    expect(units.every((u) => u.kind === "single")).toBe(true);
  });

  it("collapses two colliding events into a bracketed cluster", () => {
    const a = mockEvent({ timestamp: "2024-01-01T11:00:00" });
    const b = mockEvent({ timestamp: "2024-01-01T11:05:00" });
    const { units } = layoutDayEvents([a, b], dayStart, totalMinutes);
    expect(units).toHaveLength(1);
    const [unit] = units;
    if (unit.kind !== "cluster") throw new Error("expected a cluster");
    expect(unit.events).toHaveLength(2);
    // CLUSTER_HEAD(20) + n*ROW_H(34) + (n-1)*ROW_GAP(5)
    expect(unit.height).toBe(20 + 2 * 34 + 1 * 5);
  });

  it("collapses 4 colliding events into a single cluster of 4 rows", () => {
    const events = [11, 12, 13, 14].map((m) => mockEvent({ timestamp: `2024-01-01T11:${String(m).padStart(2, "0")}:00` }));
    const { units } = layoutDayEvents(events, dayStart, totalMinutes);
    expect(units).toHaveLength(1);
    const [unit] = units;
    if (unit.kind !== "cluster") throw new Error("expected a cluster");
    expect(unit.events).toHaveLength(4);
  });

  it("never merges a gap-confidence event into a cluster, even when it overlaps a real event, but still keeps them from overlapping", () => {
    const real = mockEvent({ confidence: "proven", timestamp: "2024-01-01T11:00:00" });
    const gap = mockEvent({ confidence: "gap", timestamp: "2024-01-01T11:05:00" });
    const { units } = layoutDayEvents([real, gap], dayStart, totalMinutes);
    expect(units).toHaveLength(2);
    expect(units.every((u) => u.kind === "single")).toBe(true);
    const [first, second] = [...units].sort((x, y) => x.top - y.top);
    expect(second.top).toBeGreaterThanOrEqual(first.top + first.height);
  });

  it("pushes a later unit down (cursor) rather than letting it overlap the cluster above it", () => {
    const a = mockEvent({ timestamp: "2024-01-01T11:00:00" });
    const b = mockEvent({ timestamp: "2024-01-01T11:05:00" });
    // Doesn't naturally overlap b (gap to b's natural bottom is exactly UNIT_GAP), but the
    // cluster's rendered height (header + 2 rows) extends well past that natural position.
    const c = mockEvent({ timestamp: "2024-01-01T11:55:00" });
    const { units } = layoutDayEvents([a, b, c], dayStart, totalMinutes);
    const cluster = units.find((u) => u.kind === "cluster");
    const single = units.find((u) => u.kind === "single");
    expect(cluster).toBeDefined();
    expect(single).toBeDefined();
    expect(single!.top).toBeGreaterThanOrEqual(cluster!.top + cluster!.height);
  });
});

describe("isDimmedBySourceFilter", () => {
  it("never dims when the filter is 'all'", () => {
    expect(isDimmedBySourceFilter(mockEvent({ source: "github" }), "all")).toBe(false);
  });

  it("does not dim an event matching the active filter", () => {
    expect(isDimmedBySourceFilter(mockEvent({ source: "github" }), "github")).toBe(false);
  });

  it("dims an event whose source doesn't match the active filter", () => {
    expect(isDimmedBySourceFilter(mockEvent({ source: "slack" }), "github")).toBe(true);
  });

  it("always dims a gap-confidence event once a filter is active, regardless of its source", () => {
    expect(isDimmedBySourceFilter(mockEvent({ source: "github", confidence: "gap" }), "github")).toBe(true);
  });
});

describe("Timeline page — cluster collapse (1a)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRunAgent).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false } as any);
  });

  it("collapses colliding events into a slim-row cluster instead of overlapping cards", () => {
    const events = [
      mockEvent({ source: "github", timestamp: todayAt(11, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "slack", timestamp: todayAt(11, 5), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    const { container } = render(<Timeline />);

    expect(screen.getByText("2 close events")).toBeInTheDocument();
    expect(screen.getByText("Event A")).toBeInTheDocument();
    expect(screen.getByText("Event B")).toBeInTheDocument();
    // Cluster members render as plain rows, not full TimelineBlock cards.
    expect(container.querySelectorAll("article[role='button']")).toHaveLength(0);
  });

  it("leaves non-colliding events as full, untouched proportional cards", () => {
    const events = [
      mockEvent({ source: "github", timestamp: todayAt(9, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "slack", timestamp: todayAt(11, 0), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    const { container } = render(<Timeline />);

    expect(screen.queryByText(/close events/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("article[role='button']")).toHaveLength(2);
  });

  it("preserves confidence-tier border styling on an unclustered card", () => {
    const events = [
      mockEvent({ source: "github", confidence: "estimated", timestamp: todayAt(9, 0), event_metadata: { title: "Event A" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    render(<Timeline />);
    expect(screen.getByText("Event A").closest("article")).toHaveClass("border-dashed");
  });

  it("preserves each member's own confidence-tier border style inside a cluster", () => {
    const events = [
      mockEvent({ source: "github", confidence: "proven", timestamp: todayAt(11, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "slack", confidence: "estimated", timestamp: todayAt(11, 5), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    render(<Timeline />);
    expect(screen.getByText("Event A").closest("button")).toHaveClass("border-solid");
    expect(screen.getByText("Event B").closest("button")).toHaveClass("border-dashed");
  });
});

describe("Timeline page — source filter (1d)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRunAgent).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false } as any);
  });

  it("does not show the filter row when the day has only one source", () => {
    const events = [
      mockEvent({ source: "github", timestamp: todayAt(9, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "github", timestamp: todayAt(11, 0), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    render(<Timeline />);
    expect(screen.queryByRole("button", { name: "All" })).not.toBeInTheDocument();
  });

  it("dims only non-matching sources when a filter chip is active", () => {
    const events = [
      mockEvent({ source: "github", timestamp: todayAt(9, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "slack", timestamp: todayAt(11, 0), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    render(<Timeline />);
    fireEvent.click(screen.getByRole("button", { name: "GitHub" }));

    expect(screen.getByText("Event A").closest("article")).not.toHaveAttribute("aria-hidden");
    expect(screen.getByText("Event B").closest("article")).toHaveAttribute("aria-hidden", "true");
  });

  it("resets to All (clears dimming) when the active chip is tapped again", () => {
    const events = [
      mockEvent({ source: "github", timestamp: todayAt(9, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "slack", timestamp: todayAt(11, 0), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    render(<Timeline />);
    const githubChip = screen.getByRole("button", { name: "GitHub" });
    fireEvent.click(githubChip);
    expect(screen.getByText("Event B").closest("article")).toHaveAttribute("aria-hidden", "true");

    fireEvent.click(githubChip);
    expect(screen.getByText("Event A").closest("article")).not.toHaveAttribute("aria-hidden");
    expect(screen.getByText("Event B").closest("article")).not.toHaveAttribute("aria-hidden");
  });

  it("dims a non-matching row inside a cluster without dimming the whole group", () => {
    const events = [
      mockEvent({ source: "github", timestamp: todayAt(11, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "slack", timestamp: todayAt(11, 5), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    render(<Timeline />);
    fireEvent.click(screen.getByRole("button", { name: "GitHub" }));

    expect(screen.getByText("1 github events")).toBeInTheDocument();
    expect(screen.getByText("Event A").closest("button")).not.toHaveAttribute("aria-hidden");
    expect(screen.getByText("Event B").closest("button")).toHaveAttribute("aria-hidden", "true");
  });

  it("resets the filter when navigating to a different day", () => {
    const events = [
      mockEvent({ source: "github", timestamp: todayAt(9, 0), event_metadata: { title: "Event A" } }),
      mockEvent({ source: "slack", timestamp: todayAt(11, 0), event_metadata: { title: "Event B" } }),
    ];
    vi.mocked(useTimeline).mockReturnValue({ data: events, isLoading: false, isError: false } as any);

    render(<Timeline />);
    const githubChip = screen.getByRole("button", { name: "GitHub" });
    fireEvent.click(githubChip);
    expect(githubChip).toHaveClass("border-accent");

    fireEvent.click(screen.getByRole("button", { name: "Next day" }));
    expect(screen.getByRole("button", { name: "GitHub" })).not.toHaveClass("border-accent");
  });
});
