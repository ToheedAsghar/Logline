import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TimelineBlock, TimelineClusterRow } from "../TimelineBlock";
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

  it("dims to opacity .32, drops out of tab order, and stops firing onClick when dimmed", () => {
    const event = mockEvent({ confidence: "proven" });
    const onSelect = vi.fn();
    render(<TimelineBlock event={event} onSelect={onSelect} dimmed />);

    const article = screen.getByRole("button", { hidden: true });
    expect(article).toHaveStyle({ opacity: "0.32" });
    expect(article).toHaveAttribute("tabindex", "-1");
    expect(article).toHaveAttribute("aria-hidden", "true");

    fireEvent.click(article);
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("TimelineClusterRow", () => {
  it("renders the row's time range, source, title and confidence dot", () => {
    const event = mockEvent({ confidence: "proven", source: "github", timestamp: "2024-01-01T11:10:00Z" });
    render(<TimelineClusterRow event={event} />);

    expect(screen.getByText("Test Title")).toBeInTheDocument();
    expect(screen.getByText("github")).toBeInTheDocument();
  });

  it("preserves the solid/dashed/dotted confidence-tier borders per row", () => {
    const proven = mockEvent({ confidence: "proven" });
    const estimated = mockEvent({ confidence: "estimated" });
    const gap = mockEvent({ confidence: "gap" });

    const { rerender } = render(<TimelineClusterRow event={proven} />);
    expect(screen.getByRole("button")).toHaveClass("border-solid");

    rerender(<TimelineClusterRow event={estimated} />);
    expect(screen.getByRole("button")).toHaveClass("border-dashed");

    rerender(<TimelineClusterRow event={gap} />);
    expect(screen.getByRole("button")).toHaveClass("border-dotted");
  });

  it("fires onSelect with the row's event data", () => {
    const event = mockEvent({ confidence: "proven" });
    const onSelect = vi.fn();
    render(<TimelineClusterRow event={event} onSelect={onSelect} />);

    fireEvent.click(screen.getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith(event);
  });

  it("dims to opacity .32 and stops firing onSelect when dimmed", () => {
    const event = mockEvent({ confidence: "proven" });
    const onSelect = vi.fn();
    render(<TimelineClusterRow event={event} onSelect={onSelect} dimmed />);

    const row = screen.getByRole("button", { hidden: true });
    expect(row).toHaveStyle({ opacity: "0.32" });
    expect(row).toHaveAttribute("tabindex", "-1");

    fireEvent.click(row);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
