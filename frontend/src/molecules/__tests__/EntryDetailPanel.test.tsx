import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { EntryDetailPanel } from "../EntryDetailPanel";
import type { Event } from "@/repositories/types";

vi.mock("@/repositories/hooks", () => ({
  useUpdateEvent: vi.fn(),
  useDeleteEvent: vi.fn(),
}));

import { useUpdateEvent, useDeleteEvent } from "@/repositories/hooks";

const mockEvent = (overrides: Partial<Event>): Event => ({
  id: 1,
  type: "test_event",
  source: "github",
  confidence: "proven",
  timestamp: "2024-01-01T10:00:00Z",
  created_at: "2024-01-01T10:00:00Z",
  event_metadata: {
    title: "Initial Title",
    summary: "Initial Summary",
    custom_field: "Custom Value",
  },
  ...overrides,
});

describe("EntryDetailPanel", () => {
  const mockOnClose = vi.fn();
  
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders event data correctly", () => {
    vi.mocked(useUpdateEvent).mockReturnValue({ mutate: vi.fn() } as any);
    vi.mocked(useDeleteEvent).mockReturnValue({ mutate: vi.fn() } as any);

    render(<EntryDetailPanel event={mockEvent({})} onClose={mockOnClose} />);
    
    expect(screen.getByDisplayValue("Initial Title")).toBeInTheDocument();
    expect(screen.getByText("Initial Summary")).toBeInTheDocument();
    expect(screen.getByText("github")).toBeInTheDocument(); // source is rendered lowercase in DOM, styled uppercase
    expect(screen.getByText("custom field")).toBeInTheDocument(); // Evidence key
    expect(screen.getByText("Custom Value")).toBeInTheDocument(); // Evidence value
  });

  it("title edit and save flow works", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useUpdateEvent).mockReturnValue({ mutate: updateMutate } as any);
    vi.mocked(useDeleteEvent).mockReturnValue({ mutate: vi.fn() } as any);

    render(<EntryDetailPanel event={mockEvent({})} onClose={mockOnClose} />);
    
    const titleInput = screen.getByDisplayValue("Initial Title");
    
    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, "New Title");
    fireEvent.blur(titleInput); // Triggers saveTitle
    
    expect(updateMutate).toHaveBeenCalledWith({ id: 1, patch: { title: "New Title" } });
  });

  it("summary edit-save-cancel flows work", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useUpdateEvent).mockReturnValue({ mutate: updateMutate } as any);
    vi.mocked(useDeleteEvent).mockReturnValue({ mutate: vi.fn() } as any);

    render(<EntryDetailPanel event={mockEvent({})} onClose={mockOnClose} />);
    
    // Start editing
    const editBtn = screen.getByRole("button", { name: "Edit" });
    fireEvent.click(editBtn);
    
    // Should turn into a textarea
    const summaryTextarea = screen.getByDisplayValue("Initial Summary");
    
    // Cancel edit
    await userEvent.type(summaryTextarea, " changed");
    const cancelBtn = screen.getByRole("button", { name: "Cancel" });
    fireEvent.click(cancelBtn);
    
    // Verify it reverted (the div should be back, button should be back)
    expect(screen.getByText("Initial Summary")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Initial Summary changed")).not.toBeInTheDocument();
    
    // Edit again and save
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const summaryTextarea2 = screen.getByDisplayValue("Initial Summary");
    await userEvent.clear(summaryTextarea2);
    await userEvent.type(summaryTextarea2, "Saved Summary");
    
    const saveBtn = screen.getByRole("button", { name: "Save summary" });
    fireEvent.click(saveBtn);
    
    expect(updateMutate).toHaveBeenCalledWith({ id: 1, patch: { summary: "Saved Summary" } });
  });

  it("the 'estimated -> Confirm' banner only shows for estimated confidence and calls update on click", () => {
    const updateMutate = vi.fn();
    vi.mocked(useUpdateEvent).mockReturnValue({ mutate: updateMutate } as any);
    vi.mocked(useDeleteEvent).mockReturnValue({ mutate: vi.fn() } as any);

    const { rerender } = render(<EntryDetailPanel event={mockEvent({ confidence: "proven" })} onClose={mockOnClose} />);
    
    expect(screen.queryByText(/This time was estimated/)).not.toBeInTheDocument();
    
    rerender(<EntryDetailPanel event={mockEvent({ confidence: "estimated" })} onClose={mockOnClose} />);
    
    const confirmBtn = screen.getByText(/This time was estimated/).closest("button");
    expect(confirmBtn).toBeInTheDocument();
    
    if (confirmBtn) {
      fireEvent.click(confirmBtn);
      expect(updateMutate).toHaveBeenCalledWith({ id: 1, patch: { confidence: "proven" } });
    }
  });

  it("delete requires the two-step confirm before calling delete", () => {
    const deleteMutate = vi.fn();
    vi.mocked(useUpdateEvent).mockReturnValue({ mutate: vi.fn() } as any);
    vi.mocked(useDeleteEvent).mockReturnValue({ mutate: deleteMutate } as any);

    render(<EntryDetailPanel event={mockEvent({})} onClose={mockOnClose} />);
    
    const deleteBtn = screen.getByRole("button", { name: "Delete entry" });
    fireEvent.click(deleteBtn);
    
    // Shouldn't have mutated yet
    expect(deleteMutate).not.toHaveBeenCalled();
    
    // Now it should show the confirmation state
    expect(screen.getByText("Delete this entry?")).toBeInTheDocument();
    
    // Click confirm delete
    const confirmDeleteBtn = screen.getAllByRole("button", { name: "Delete entry" })[0];
    fireEvent.click(confirmDeleteBtn);
    
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.any(Object));
  });
});
