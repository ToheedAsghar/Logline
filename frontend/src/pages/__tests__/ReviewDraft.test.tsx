import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { formatMinutes, getTodayLocalDate, minutesToHHMM, parseLocalDate, parseTimeToMinutes } from "@/common/utils";
import { ReviewDraft, describeApiError } from "../ReviewDraft";
import { ApiError } from "@/repositories/api";
import type { WorkLogDraft, ReconciliationResult } from "@/repositories/types";

vi.mock("@/repositories/hooks", () => ({
  useCurrentDraft: vi.fn(),
  useGenerateDraft: vi.fn(),
  useApproveDraft: vi.fn(),
  useDiscardDraft: vi.fn(),
}));

import { useApproveDraft, useCurrentDraft, useDiscardDraft, useGenerateDraft } from "@/repositories/hooks";

const mockDraft: WorkLogDraft = {
  entries: [
    {
      entry_id: 41,
      origin: "evidence",
      date: "2026-07-24",
      project: "logline",
      allocations: [{ block_id: 1, minutes: 90, date: "2026-07-24" }],
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
  residual_unassigned_minutes: [{ block_id: 2, minutes: 15, date: "2026-07-24" }],
  tracked_wall_clock_minutes: 75,
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

const mockResult: ReconciliationResult = {
  draft_id: 9,
  state: "active",
  date_range_start: "2026-07-24",
  date_range_end: "2026-07-24",
  generated_at: "2026-07-24T12:00:00Z",
  draft: mockDraft,
  verification: mockVerification,
};

function mockGenerateWithDraft(draft = mockDraft) {
  (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
    mutate: (_params: unknown, options: { onSuccess: (data: ReconciliationResult) => void }) => {
      options.onSuccess({ ...mockResult, draft });
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
  let approveMutateMock: ReturnType<
    typeof vi.fn<
      (payload: { date_range_start: string; date_range_end: string; draft_id: number; draft: WorkLogDraft }) => void
    >
  >;
  let discardMutateMock: ReturnType<typeof vi.fn<(draftId: number) => void>>;

  beforeEach(() => {
    vi.clearAllMocks();
    generateMutateMock = vi.fn();
    approveMutateMock = vi.fn();
    discardMutateMock = vi.fn();

    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });

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

    (useDiscardDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: discardMutateMock,
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

  it("loads a persisted server draft on mount without generating again", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    expect(await screen.findByText("Initial description from AI")).toBeInTheDocument();
    expect(generateMutateMock).not.toHaveBeenCalled();
  });

  it("shows tracked and allocated as separate header figures", async () => {
    mockGenerateWithDraft();

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    await waitFor(() => {
      expect(screen.getByText("TRACKED")).toBeInTheDocument();
    });
    expect(screen.getByText("ALLOCATED")).toBeInTheDocument();
  });

  it("reports allocated time exceeding tracked time rather than collapsing them into one number", async () => {
    mockGenerateWithDraft();

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    await waitFor(() => {
      expect(screen.getByText("TRACKED")).toBeInTheDocument();
    });

    expect(screen.getByText("TRACKED").nextElementSibling).toHaveTextContent(formatMinutes(75));
    expect(screen.getByText("ALLOCATED").nextElementSibling).toHaveTextContent(formatMinutes(90));
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
      mutate: (
        payload: { date_range_start: string; date_range_end: string; draft_id: number; draft: WorkLogDraft },
        options: { onSuccess: () => void },
      ) => {
        approveMutateMock(payload);
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
    const approvedPayload = approveMutateMock.mock.calls[0][0];
    expect(approvedPayload.date_range_start).toBe(mockResult.date_range_start);
    expect(approvedPayload.date_range_end).toBe(mockResult.date_range_end);
    expect(approvedPayload.draft_id).toBe(mockResult.draft_id);
    expect(approvedPayload.draft.entries[0].description).toBe("Final edited description");

    await waitFor(() => {
      expect(screen.getByText(/Draft entries successfully approved/i)).toBeInTheDocument();
    });
  });

  it("adds genuinely manual time even when no residual tracker time exists", async () => {
    mockGenerateWithDraft({ ...mockDraft, residual_unassigned_minutes: [] });

    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    await waitFor(() => expect(screen.getByText("Initial description from AI")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Add a block the tracker missed/i }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Edit(?:ing)?$/ })).toHaveLength(2);
    expect(screen.getAllByText("New manual work block")).not.toHaveLength(0);
  });

  it("refetches the exact newly selected day when using the date arrows", () => {
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Previous day" }));

    const previous = parseLocalDate(getTodayLocalDate());
    previous.setDate(previous.getDate() - 1);
    const expected = `${previous.getFullYear()}-${String(previous.getMonth() + 1).padStart(2, "0")}-${String(previous.getDate()).padStart(2, "0")}`;
    expect(useCurrentDraft).toHaveBeenLastCalledWith({ date_range_start: expected, date_range_end: expected });
  });

  it("regenerates an active persisted scope by replacing its server draft ID", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Regenerate/i }));

    expect(generateMutateMock).toHaveBeenCalledWith(
      expect.objectContaining({ replace_draft_id: mockResult.draft_id }),
      expect.any(Object),
    );
  });

  it("shows unaccounted time again after regenerating a draft where it was ignored", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    (useGenerateDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_params: unknown, options: { onSuccess: (data: ReconciliationResult) => void }) => {
        options.onSuccess({ ...mockResult, draft_id: mockResult.draft_id + 1 });
      },
      isPending: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Ignore" }));
    expect(screen.queryByText(/^15m unaccounted$/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    expect(await screen.findByText(/^15m unaccounted$/i)).toBeInTheDocument();
  });

  it("restores the server baseline when discarding edits without changing scope", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByDisplayValue("Initial description from AI"), {
      target: { value: "Unsaved local edit" },
    });

    fireEvent.click(screen.getByRole("button", { name: "DAY" }));

    expect(screen.getByText("Initial description from AI")).toBeInTheDocument();
    expect(screen.queryByText("Unsaved local edit")).not.toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("moves assigned residual minutes out of the residual pool before approval", async () => {
    mockGenerateWithDraft();
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    await screen.findByText("Initial description from AI");

    fireEvent.click(screen.getByRole("button", { name: "Add a block" }));
    fireEvent.click(screen.getByRole("button", { name: /Save day/i }));

    const approvedPayload = approveMutateMock.mock.calls[0][0];
    expect(approvedPayload.draft.residual_unassigned_minutes).toEqual([]);
    expect(approvedPayload.draft.entries[1]).toMatchObject({
      origin: "manual",
      allocations: [{ block_id: 2, minutes: 15 }],
    });
  });

  it("renders an approved persisted draft as read-only", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { ...mockResult, state: "approved" },
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    await screen.findByText("Initial description from AI");
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add a block the tracker missed/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Saved/i })).toBeDisabled();
  });

  it("renders a Discard draft action for an active draft", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    await screen.findByText("Initial description from AI");
    expect(screen.getByRole("button", { name: /Discard draft/i })).toBeEnabled();
  });

  it("discards the draft after confirmation and returns to the empty state", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    (useDiscardDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_id: number, options: { onSuccess: () => void }) => {
        discardMutateMock(_id);
        options.onSuccess();
      },
      isPending: false,
      isError: false,
      error: null,
    });
    const confirmSpy = vi.spyOn(window, "confirm");
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    await screen.findByText("Initial description from AI");

    fireEvent.click(screen.getByRole("button", { name: /Discard draft/i }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Discard this reconciliation draft/i);
    expect(dialog).toHaveTextContent(/available to reconcile again/i);
    fireEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));

    expect(discardMutateMock).toHaveBeenCalledWith(mockResult.draft_id);
    await waitFor(() => {
      expect(screen.getByText(/No draft loaded/i)).toBeInTheDocument();
    });
    expect(screen.queryByText("Initial description from AI")).not.toBeInTheDocument();
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("does not discard when the confirmation is cancelled", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    await screen.findByText("Initial description from AI");

    fireEvent.click(screen.getByRole("button", { name: /Discard draft/i }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(discardMutateMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Initial description from AI")).toBeInTheDocument();
  });

  it("hides the Discard draft action for an approved draft", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { ...mockResult, state: "approved" },
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    await screen.findByText("Initial description from AI");
    expect(screen.queryByRole("button", { name: /Discard draft/i })).not.toBeInTheDocument();
  });

  it("surfaces a server error when discarding fails", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    (useDiscardDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: (_id: number, options: { onError: (e: unknown) => void }) => {
        options.onError(new ApiError(409, { detail: "This reconciliation draft is approved and cannot be discarded." }));
      },
      isPending: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    await screen.findByText("Initial description from AI");

    fireEvent.click(screen.getByRole("button", { name: /Discard draft/i }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/draft changed on the server/i);
  });

  it("returns a discarded evidence entry's measured time to residual and permits saving zero entries", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));

    fireEvent.click(screen.getByRole("button", { name: /Save day/i }));

    const approvedPayload = approveMutateMock.mock.calls[0][0];
    expect(approvedPayload.draft.entries).toEqual([]);
    expect(approvedPayload.draft.residual_unassigned_minutes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ block_id: 1, minutes: 90 }),
        expect.objectContaining({ block_id: 2, minutes: 15 }),
      ]),
    );
  });

  it("keeps conservation when reducing a measured allocation", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "1h" }));
    fireEvent.click(screen.getByRole("button", { name: /Save day/i }));

    const approvedPayload = approveMutateMock.mock.calls[0][0];
    expect(approvedPayload.draft.entries[0].allocations[0].minutes).toBe(60);
    expect(approvedPayload.draft.residual_unassigned_minutes).toContainEqual(
      expect.objectContaining({ block_id: 1, minutes: 30 }),
    );
  });

  it("adopts a covering range and lets truly manual work choose a day in that range", async () => {
    const rangeResult: ReconciliationResult = {
      ...mockResult,
      date_range_start: "2026-07-23",
      date_range_end: "2026-07-25",
    };
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: rangeResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);

    expect(await screen.findByText(/2026-07-23 to 2026-07-25/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Add a block the tracker missed/i }));
    const workDate = screen.getByLabelText("Work date");
    fireEvent.change(workDate, { target: { value: "2026-07-25" } });
    fireEvent.click(screen.getByRole("button", { name: /Save day/i }));

    const approvedPayload = approveMutateMock.mock.calls[0][0];
    expect(approvedPayload.date_range_start).toBe("2026-07-23");
    expect(approvedPayload.date_range_end).toBe("2026-07-25");
    expect(approvedPayload.draft.entries.at(-1)).toMatchObject({ origin: "manual", date: "2026-07-25" });
  });

  it("moves range arrows to the adjacent day outside the covering range", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { ...mockResult, date_range_start: "2026-07-23", date_range_end: "2026-07-25" },
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    await screen.findByText(/2026-07-23 to 2026-07-25/);

    fireEvent.click(screen.getByRole("button", { name: "Next day" }));

    expect(useCurrentDraft).toHaveBeenCalledWith({ date_range_start: "2026-07-26", date_range_end: "2026-07-26" });
  });

  it("does not regenerate a locally edited draft when discard is cancelled", async () => {
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: mockResult,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<MemoryRouter><ReviewDraft /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByDisplayValue("Initial description from AI"), {
      target: { value: "Unsaved local edit" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(generateMutateMock).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
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

  it("describes a 409 as a simple reload conflict", () => {
    const described = describeApiError(new ApiError(409, { detail: "This draft is no longer active." }), "approve");
    expect(described.title).toMatch(/draft changed/i);
    expect(described.detail).toMatch(/no longer active/i);
  });

  it("names the discard action in its fallback title", () => {
    const described = describeApiError(new ApiError(500, { detail: "boom" }), "discard");
    expect(described.title).toMatch(/could not discard/i);
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
    (useCurrentDraft as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    });
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
        options.onSuccess(mockResult);
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
    generateHandlers!.onSuccess(mockResult);
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
          ...mockResult,
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
