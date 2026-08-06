import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { formatMinutes, minutesToHHMM, parseTimeToMinutes } from "@/common/utils";
import { ReviewDraft } from "../ReviewDraft";
import type { WorkLogDraft, ReconciliationResult } from "@/repositories/types";

vi.mock("@/repositories/hooks", () => ({
  useGenerateDraft: vi.fn(),
  useApproveDraft: vi.fn(),
}));

import { useGenerateDraft, useApproveDraft } from "@/repositories/hooks";

const mockDraft: WorkLogDraft = {
  entries: [
    {
      date: "2026-07-24",
      project: "logline",
      allocations: [{ block_id: 1, minutes: 90 }],
      tag: "Coding",
      description: "Initial description from AI",
      source_remote_event_ids: ["gh:pr:1"],
      review_reason: "AI was unsure about duration",
    },
  ],
  reminders: [
    {
      note: "Did you review PR #42?",
      source: "github",
      day: "2026-07-24",
      source_remote_event_ids: ["gh:pr:42"],
    },
  ],
  residual_unassigned_minutes: [{ block_id: 2, minutes: 15 }],
};

const mockVerification: ReconciliationResult["verification"] = {
  passed: true,
  issues: [
    {
      severity: "warning",
      check: "duplicate_reminder",
      detail: "Remote event gh:pr:42 is covered by duplicate reminders",
    },
  ],
};

function mockGenerateWithDraft() {
  (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
    mutate: (_params: unknown, options: { onSuccess: (data: ReconciliationResult) => void }) => {
      options.onSuccess({ draft: mockDraft, verification: mockVerification });
    },
    isPending: false,
    isError: false,
    error: null,
  });
}

describe("ReviewDraft utilities", () => {
  it("formats minutes into human readable Xh Ym strings", () => {
    expect(formatMinutes(0)).toBe("0m");
    expect(formatMinutes(45)).toBe("45m");
    expect(formatMinutes(60)).toBe("1h");
    expect(formatMinutes(474)).toBe("7h 54m");
  });

  it("converts minutes to HH:MM strings", () => {
    expect(minutesToHHMM(0)).toBe("00:00");
    expect(minutesToHHMM(90)).toBe("01:30");
    expect(minutesToHHMM(474)).toBe("07:54");
  });

  it("parses time strings into total minutes", () => {
    expect(parseTimeToMinutes("01:30")).toBe(90);
    expect(parseTimeToMinutes("45")).toBe(45);
    expect(parseTimeToMinutes("1.5")).toBe(90);
  });
});

describe("ReviewDraft Component", () => {
  let generateMutateMock: ReturnType<typeof vi.fn>;
  let approveMutateMock: ReturnType<typeof vi.fn<(draft: WorkLogDraft) => void>>;

  beforeEach(() => {
    vi.clearAllMocks();
    generateMutateMock = vi.fn();
    approveMutateMock = vi.fn();

    (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: generateMutateMock,
      isPending: false,
      isError: false,
      error: null,
    });

    (useApproveDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: approveMutateMock,
      isPending: false,
      isError: false,
      error: null,
    });
  });

  it("renders empty state initially with Generate Draft button", () => {
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    expect(screen.getByText(/Review draft/i)).toBeInTheDocument();
    expect(screen.getByText(/No draft loaded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate/i })).toBeInTheDocument();
  });

  it("edits entries in local React state only without calling API prematurely", async () => {
    mockGenerateWithDraft();

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    await waitFor(() => {
      expect(screen.getByText("Initial description from AI")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    const descriptionInput = screen.getByDisplayValue("Initial description from AI");
    fireEvent.change(descriptionInput, { target: { value: "Updated local description" } });

    expect(screen.getByDisplayValue("Updated local description")).toBeInTheDocument();
    expect(approveMutateMock).not.toHaveBeenCalled();
  });

  it("sends the edited payload to approve and shows the success banner on completion", async () => {
    mockGenerateWithDraft();
    (useApproveDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (draft: WorkLogDraft, options: { onSuccess: () => void }) => {
        approveMutateMock(draft);
        options.onSuccess();
      },
      isPending: false,
      isError: false,
      error: null,
    });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    await waitFor(() => {
      expect(screen.getByText("Initial description from AI")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    const descriptionInput = screen.getByDisplayValue("Initial description from AI");
    fireEvent.change(descriptionInput, { target: { value: "Final edited description" } });

    const approveButton = screen.getByRole("button", { name: /Save day/i });
    fireEvent.click(approveButton);

    expect(approveMutateMock).toHaveBeenCalledTimes(1);
    const approvedPayload = approveMutateMock.mock.calls[0][0] as WorkLogDraft;
    expect(approvedPayload.entries[0].description).toBe("Final edited description");

    await waitFor(() => {
      expect(screen.getByText(/Draft entries successfully approved/i)).toBeInTheDocument();
    });
  });

  it("does not crash and still shows empty state when generate mutation is in error state", () => {
    (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: generateMutateMock,
      isPending: false,
      isError: true,
      error: new Error("Network error"),
    });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    expect(screen.getByText(/No draft loaded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate/i })).toBeEnabled();
  });

  it("keeps the draft visible and Save day enabled when approve mutation errors", async () => {
    mockGenerateWithDraft();

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    await waitFor(() => {
      expect(screen.getByText("Initial description from AI")).toBeInTheDocument();
    });

    (useApproveDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: approveMutateMock,
      isPending: false,
      isError: true,
      error: new Error("Server error"),
    });

    expect(screen.getByText("Initial description from AI")).toBeInTheDocument();
  });
});
