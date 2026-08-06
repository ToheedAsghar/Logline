import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { formatMinutes, minutesToHHMM, parseTimeToMinutes } from "@/common/utils";
import { ReviewDraft, describeApiError } from "../ReviewDraft";
import { ApiError } from "@/repositories/api";
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
});

describe("describeApiError", () => {
  it("names a 404 as the endpoint being missing rather than a generic failure", () => {
    const described = describeApiError(new ApiError(404, { detail: "Not Found" }), "generate");
    expect(described.title).toMatch(/isn't available on the server/i);
    expect(described.detail).toMatch(/reconciliation/i);
  });

  it("surfaces the verifier's individual issues from a 422 rejection", () => {
    const error = new ApiError(422, {
      detail: {
        message: "Draft failed verification against its evidence and was not saved.",
        issues: [
          { severity: "error", check: "conservation", detail: "block 1 is overcharged by 360 minutes", block_id: 1 },
        ],
      },
    });

    const described = describeApiError(error, "approve");
    expect(described.detail).toMatch(/was not saved/i);
    expect(described.issues).toHaveLength(1);
    expect(described.issues?.[0].check).toBe("conservation");
  });

  it("summarises FastAPI's own field-validation shape for a 422", () => {
    const error = new ApiError(422, {
      detail: [{ loc: ["body", "date_range_start"], msg: "must be on or before date_range_end" }],
    });

    const described = describeApiError(error, "generate");
    expect(described.detail).toMatch(/date_range_start: must be on or before date_range_end/);
  });

  it("treats a non-ApiError as an unreachable server", () => {
    const described = describeApiError(new TypeError("Failed to fetch"), "approve");
    expect(described.title).toMatch(/could not reach the server/i);
    expect(described.detail).toMatch(/nothing was saved/i);
  });
});

describe("ReviewDraft failure states", () => {
  let generateMutateMock: ReturnType<typeof vi.fn>;
  let approveMutateMock: ReturnType<typeof vi.fn>;

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

  it("shows a visible, dismissible error when Regenerate fails instead of returning silently to idle", async () => {
    (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_params: unknown, options: { onError: (error: unknown) => void }) => {
        options.onError(new ApiError(404, { detail: "Not Found" }));
      },
      isPending: false,
      isError: true,
      error: null,
    });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/isn't available on the server/i);

    fireEvent.click(screen.getByRole("button", { name: /Dismiss error/i }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("shows the verifier's rejection when Save day fails, and does not claim success", async () => {
    (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_params: unknown, options: { onSuccess: (data: ReconciliationResult) => void }) => {
        options.onSuccess({ draft: mockDraft, verification: mockVerification });
      },
      isPending: false,
      isError: false,
      error: null,
    });
    (useApproveDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_params: unknown, options: { onError: (error: unknown) => void }) => {
        options.onError(
          new ApiError(422, {
            detail: {
              message: "Draft failed verification against its evidence and was not saved.",
              issues: [{ severity: "error", check: "conservation", detail: "block 1 is overcharged", block_id: 1 }],
            },
          }),
        );
      },
      isPending: false,
      isError: true,
      error: null,
    });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    await waitFor(() => expect(screen.getByText("Initial description from AI")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Save day/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/was not saved/i);
    expect(alert).toHaveTextContent(/conservation/);
    expect(screen.queryByText(/successfully approved and saved/i)).not.toBeInTheDocument();
  });

  it("keeps the existing draft on screen when a regenerate fails", async () => {
    let generateHandlers: { onSuccess: (d: ReconciliationResult) => void; onError: (e: unknown) => void };
    (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_params: unknown, options: typeof generateHandlers) => {
        generateHandlers = options;
      },
      isPending: false,
      isError: false,
      error: null,
    });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    generateHandlers!.onSuccess({ draft: mockDraft, verification: mockVerification });
    await waitFor(() => expect(screen.getByText("Initial description from AI")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    generateHandlers!.onError(new TypeError("Failed to fetch"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach the server/i);
    expect(screen.getByText("Initial description from AI")).toBeInTheDocument();
  });

  it("surfaces a failed verification on a draft that generated successfully", async () => {
    (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_params: unknown, options: { onSuccess: (data: ReconciliationResult) => void }) => {
        options.onSuccess({
          draft: mockDraft,
          verification: {
            passed: false,
            issues: [
              { severity: "error", check: "conservation", detail: "block 1 is overcharged by 60 minutes", block_id: 1 },
            ],
          },
        });
      },
      isPending: false,
      isError: false,
      error: null,
    });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/did not pass the evidence checks/i);
    expect(status).toHaveTextContent(/overcharged by 60 minutes/);
  });
});
