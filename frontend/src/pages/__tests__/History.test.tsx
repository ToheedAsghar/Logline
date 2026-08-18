import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Entry } from "@/repositories/types";
import History from "../History";

vi.mock("@/repositories/hooks", () => ({
  useEntries: vi.fn(),
}));

import { useEntries } from "@/repositories/hooks";

const dateLabel = (date: Date) =>
  date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

describe("History", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-12T12:00:00Z"));
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("groups approved entries by work date rather than approval date", () => {
    const entry: Entry = {
      id: 1,
      user_id: 1,
      format: "project_log",
      content: { text: "Worked on the reconciliation UI" },
      work_date: "2026-08-10",
      status: "approved",
      created_at: "2026-08-11T12:00:00Z",
      approved_at: "2026-08-11T12:00:00Z",
    };
    (useEntries as ReturnType<typeof vi.fn>).mockReturnValue({
      data: [entry],
      isLoading: false,
      isError: false,
    });

    render(<History />);

    expect(screen.getByText(dateLabel(new Date(2026, 7, 10)))).toBeInTheDocument();
    expect(screen.queryByText(dateLabel(new Date("2026-08-11T12:00:00Z")))).not.toBeInTheDocument();
  });

  it("shows the explicit duration for a genuinely manual entry", () => {
    const entry: Entry = {
      id: 2,
      user_id: 1,
      format: "project_log",
      content: { text: "Recovered untracked work", origin: "manual", manual_minutes: 45 },
      work_date: "2026-08-10",
      status: "approved",
      created_at: "2026-08-10T12:00:00Z",
      approved_at: "2026-08-10T12:00:00Z",
    };
    (useEntries as ReturnType<typeof vi.fn>).mockReturnValue({
      data: [entry],
      isLoading: false,
      isError: false,
    });

    render(<History />);

    expect(screen.getAllByText("45m")).not.toHaveLength(0);
  });
});
