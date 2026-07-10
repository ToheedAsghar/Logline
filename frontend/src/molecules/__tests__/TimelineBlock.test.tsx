import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TimelineBlock } from "../TimelineBlock";
import type { Event } from "@/repositories/types";

const mockEvent = (overrides: Partial<Event>): Event => ({
  id: 1,
  type: "test_event",
  source: "github",
  confidence: "proven",
  timestamp: "2024-01-01T10:00:00Z",
  created_at: "2024-01-01T10:00:00Z",
  event_metadata: {
    title: "Test Title",
    summary: "Test Summary",
  },
  ...overrides,
});

describe("TimelineBlock", () => {
  it("renders correctly for proven confidence tier", () => {
    const event = mockEvent({ confidence: "proven", source: "github" });
    render(<TimelineBlock event={event} />);
    
    expect(screen.getByText("Test Title")).toBeInTheDocument();
    expect(screen.getByText("Test Summary")).toBeInTheDocument();
    expect(screen.getByText("github")).toBeInTheDocument();
  });

  it("renders correctly for estimated confidence tier", () => {
    const event = mockEvent({ confidence: "estimated", source: "slack" });
    render(<TimelineBlock event={event} />);
    
    expect(screen.getByText("slack")).toBeInTheDocument();
  });

  it("renders correctly for gap confidence tier", () => {
    const event = mockEvent({ confidence: "gap", source: "system" });
    render(<TimelineBlock event={event} />);
    
    expect(screen.getByText("system")).toBeInTheDocument();
  });

  it("renders correctly for personal (non-work) source", () => {
    // A personal event overrides confidence to show as personal tier visually
    const event = mockEvent({ confidence: "proven", source: "personal" });
    render(<TimelineBlock event={event} />);
    
    expect(screen.getByText("personal")).toBeInTheDocument();
  });

  it("fires onClick with the correct event data", () => {
    const event = mockEvent({ confidence: "proven" });
    const onSelect = vi.fn();
    render(<TimelineBlock event={event} onSelect={onSelect} />);
    
    const article = screen.getByRole("button");
    fireEvent.click(article);
    
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(event);
  });
});
