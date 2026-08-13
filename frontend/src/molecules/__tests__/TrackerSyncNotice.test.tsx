import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { TrackerSyncNotice } from "../TrackerSyncNotice";
import { TRACKER_STALE_AFTER_MINUTES } from "@/constants/tracker";

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

describe("TrackerSyncNotice", () => {
  it("reports a recent sync without raising an alarm", () => {
    render(<TrackerSyncNotice status={{ last_synced_at: minutesAgo(3), device_count: 1 }} />);

    expect(screen.getByText(/Tracker last synced 3m ago/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("flags a sync that has stopped, which is the whole point of showing this", () => {
    render(
      <TrackerSyncNotice
        status={{ last_synced_at: minutesAgo(TRACKER_STALE_AFTER_MINUTES + 5), device_count: 1 }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/Check that the sync agent is running/);
  });

  it("does not flag a gap still inside the tolerance window", () => {
    render(
      <TrackerSyncNotice
        status={{ last_synced_at: minutesAgo(TRACKER_STALE_AFTER_MINUTES - 5), device_count: 1 }}
      />,
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distinguishes an enrolled device that has never synced from one with no device at all", () => {
    const { rerender } = render(<TrackerSyncNotice status={{ last_synced_at: null, device_count: 1 }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/nothing has synced yet/);

    rerender(<TrackerSyncNotice status={{ last_synced_at: null, device_count: 0 }} />);
    expect(screen.getByText(/No tracker device enrolled/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
