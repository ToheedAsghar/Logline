import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loading } from "@/atoms";
import { formatMinutes, getTodayLocalDate, parseLocalDate } from "@/common/utils";
import { REVIEW_DRAFT_TEXTS } from "@/constants";
import { ApiError } from "@/repositories/api";
import { ALL_ENTRY_TAGS, type BlockAllocation, type DraftEntry, type EntryTag, type ReconciliationResult, type VerificationIssue, type WorkLogDraft } from "@/repositories/types";
import { useApproveDraft, useCurrentDraft, useDiscardDraft, useGenerateDraft } from "@/repositories/hooks";
import { ConfirmDialog } from "@/molecules";
import { useUnsavedDraftGuard } from "./reviewDraft/useUnsavedDraftGuard";

export interface DescribedError {
  title: string;
  detail: string;
  issues?: VerificationIssue[];
}

const ACTION_LABEL: Record<"generate" | "approve" | "discard", string> = {
  generate: REVIEW_DRAFT_TEXTS.GENERATE_ACTION_LABEL,
  approve: REVIEW_DRAFT_TEXTS.APPROVE_ACTION_LABEL,
  discard: REVIEW_DRAFT_TEXTS.DISCARD_ACTION_LABEL,
};

const TRACKED_TIME_ERROR: DescribedError = {
  title: REVIEW_DRAFT_TEXTS.TRACKED_TIME_ERROR_TITLE,
  detail: REVIEW_DRAFT_TEXTS.TRACKED_TIME_ERROR_DETAIL,
};

function rebalanceResidual(
  residual: BlockAllocation[], previous: BlockAllocation[], next: BlockAllocation[],
): BlockAllocation[] | null {
  const byBlock = new Map(residual.map((allocation) => [allocation.block_id, { ...allocation }]));
  const order = residual.map((allocation) => allocation.block_id);
  const previousByBlock = new Map(previous.map((allocation) => [allocation.block_id, allocation]));
  const nextByBlock = new Map(next.map((allocation) => [allocation.block_id, allocation]));
  const blockIds = new Set([...previousByBlock.keys(), ...nextByBlock.keys()]);

  for (const blockId of blockIds) {
    const oldAllocation = previousByBlock.get(blockId);
    const nextAllocation = nextByBlock.get(blockId);
    const delta = (nextAllocation?.minutes ?? 0) - (oldAllocation?.minutes ?? 0);
    if (delta > 0) {
      const available = byBlock.get(blockId);
      if (!available || available.minutes < delta) return null;
      if (available.minutes === delta) byBlock.delete(blockId);
      else byBlock.set(blockId, { ...available, minutes: available.minutes - delta });
    } else if (delta < 0) {
      const returned = -delta;
      const available = byBlock.get(blockId);
      if (!order.includes(blockId)) order.push(blockId);
      byBlock.set(blockId, {
        block_id: blockId,
        minutes: (available?.minutes ?? 0) + returned,
        date: available?.date ?? oldAllocation?.date ?? nextAllocation?.date,
      });
    }
  }

  return order.flatMap((blockId) => {
    const allocation = byBlock.get(blockId);
    return allocation ? [allocation] : [];
  });
}

function describeUnprocessable(body: unknown, fallbackTitle: string): DescribedError {
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "object" && detail !== null && "issues" in detail) {
    const { message, issues } = detail as { message?: string; issues?: VerificationIssue[] };
    return {
      title: REVIEW_DRAFT_TEXTS.VERIFICATION_REJECTED_TITLE,
      detail: message ?? REVIEW_DRAFT_TEXTS.VERIFICATION_REJECTED_DEFAULT_DETAIL,
      issues: issues ?? [],
    };
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        const loc = Array.isArray(item?.loc) ? item.loc.filter((p: unknown) => p !== "body").join(".") : "";
        return loc ? `${loc}: ${item?.msg ?? "invalid"}` : String(item?.msg ?? "invalid");
      })
      .filter(Boolean);
    return {
      title: fallbackTitle,
      detail: messages.length ? `The server rejected this request — ${messages.join("; ")}` : REVIEW_DRAFT_TEXTS.INVALID_REQUEST_DETAIL,
    };
  }

  return {
    title: fallbackTitle,
    detail: typeof detail === "string" ? detail : REVIEW_DRAFT_TEXTS.INVALID_REQUEST_DETAIL,
  };
}

export function describeApiError(error: unknown, action: "generate" | "approve" | "discard"): DescribedError {
  const fallbackTitle = ACTION_LABEL[action];

  if (error instanceof ApiError) {
    if (error.status === 404) {
      return {
        title: REVIEW_DRAFT_TEXTS.FEATURE_UNAVAILABLE_TITLE,
        detail: REVIEW_DRAFT_TEXTS.FEATURE_UNAVAILABLE_DETAIL,
      };
    }
    if (error.status === 401) {
      return {
        title: REVIEW_DRAFT_TEXTS.SESSION_EXPIRED_TITLE,
        detail: REVIEW_DRAFT_TEXTS.SESSION_EXPIRED_DETAIL,
      };
    }
    if (error.status === 422) {
      return describeUnprocessable(error.body, fallbackTitle);
    }
    if (error.status === 409) {
      return {
        title: REVIEW_DRAFT_TEXTS.DRAFT_CHANGED_TITLE,
        detail: error.message || REVIEW_DRAFT_TEXTS.DRAFT_CHANGED_RELOAD_DETAIL,
      };
    }
    if (error.status >= 500) {
      return {
        title: fallbackTitle,
        detail: `The server failed while handling this request (HTTP ${error.status}). Nothing was saved.`,
      };
    }
    return { title: fallbackTitle, detail: error.message || `The request failed with status ${error.status}.` };
  }

  return {
    title: REVIEW_DRAFT_TEXTS.SERVER_UNREACHABLE_TITLE,
    detail: REVIEW_DRAFT_TEXTS.SERVER_UNREACHABLE_DETAIL,
  };
}

export function ErrorBanner({ error, onDismiss }: { error: DescribedError; onDismiss: () => void }) {
  return (
    <div
      role="alert"
      className="mb-4 rounded-md border border-[#D8B4B4] bg-[#FBF0EF] px-4 py-3 text-[#7A2E2E]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-sm">{error.title}</p>
          <p className="mt-1 text-xs leading-relaxed text-[#8A4A4A]">{error.detail}</p>
          {error.issues && error.issues.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-[#8A4A4A]">
              {error.issues.map((issue, idx) => (
                <li key={`${issue.check}-${idx}`} className="font-mono">
                  [{issue.severity}] {issue.check}
                  {issue.block_id != null ? ` (block ${issue.block_id})` : ""}
                  {issue.entry_index != null ? ` (entry ${issue.entry_index + 1})` : ""} — {issue.detail}
                </li>
              ))}
            </ul>
          )}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss error"
          className="shrink-0 rounded px-2 py-0.5 text-lg leading-none text-[#8A4A4A] transition-colors hover:bg-[#F3DEDC]"
        >
          ×
        </button>
      </div>
    </div>
  );
}
export function TagSelect({
  value,
  onChange,
}: {
  value: EntryTag;
  onChange: (tag: EntryTag) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const buttonRef = useRef<HTMLButtonElement>(null);

  const filteredTags = ALL_ENTRY_TAGS.filter((tag) =>
    tag.toLowerCase().includes(filter.toLowerCase()),
  );

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  return (
    <div className="relative inline-block w-full">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(!open)}
        aria-label="Entry tag selector"
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-1.5 rounded-md border border-[#E3DFD2] bg-[#FFFDF7] px-3 py-1.5 font-mono text-xs text-[#57564E] transition-colors hover:border-[#CFCABA] focus:border-[#14603C] focus:outline-none"
      >
        <span className="truncate">{value}</span>
        <span className="text-[10px] text-[#8A887C]">▼</span>
      </button>

      {open && (
        <>
          <button type="button" aria-label="Close tag dropdown" className="fixed inset-0 z-40 cursor-default" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-50 mt-1 max-h-56 w-56 overflow-y-auto rounded-md border border-[#E3DFD2] bg-[#FFFDF7] p-1.5 shadow-elevated">
            <input
              type="text"
              placeholder="Search tag..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="mb-1.5 w-full rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2.5 py-1 font-mono text-xs text-[#191917] focus:border-[#14603C] focus:outline-none"
              autoFocus
            />
            <div className="space-y-0.5" role="listbox">
              {filteredTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  role="option"
                  aria-selected={tag === value}
                  onClick={() => {
                    onChange(tag);
                    setOpen(false);
                    setFilter("");
                  }}
                  className={`flex w-full items-center justify-between rounded px-2.5 py-1.5 text-xs transition-colors ${
                    tag === value
                      ? "bg-[#DCEBDD] font-semibold text-[#14603C]"
                      : "text-[#191917] hover:bg-[#F5F2EA]"
                  }`}
                >
                  <span>{tag}</span>
                  {tag === value && <span className="text-[#14603C]">✓</span>}
                </button>
              ))}
              {filteredTags.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-[#8A887C]">No matching tags</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function ReviewDraft() {
  const navigate = useNavigate();
  const todayStr = useMemo(() => getTodayLocalDate(), []);
  const [startDate, setStartDate] = useState(getTodayLocalDate);
  const [endDate, setEndDate] = useState(getTodayLocalDate);
  const [pendingStartDate, setPendingStartDate] = useState(getTodayLocalDate);
  const [pendingEndDate, setPendingEndDate] = useState(getTodayLocalDate);
  const [scopeMode, setScopeMode] = useState<"DAY" | "RANGE">("DAY");
  const [pickerOpen, setPickerOpen] = useState(false);

  const [draft, setDraft] = useState<WorkLogDraft | null>(null);
  const [persistedResult, setPersistedResult] = useState<ReconciliationResult | null>(null);
  const [verification, setVerification] = useState<ReconciliationResult["verification"] | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [approveSuccess, setApproveSuccess] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [ignoredGapDraftId, setIgnoredGapDraftId] = useState<number | null>(null);
  const [generateError, setGenerateError] = useState<DescribedError | null>(null);
  const [queryErrorDismissed, setQueryErrorDismissed] = useState(false);
  const [approveError, setApproveError] = useState<DescribedError | null>(null);
  const [discardError, setDiscardError] = useState<DescribedError | null>(null);
  const [confirmDiscardOpen, setConfirmDiscardOpen] = useState(false);
  const [addBlockError, setAddBlockError] = useState<DescribedError | null>(null);

  const selectedRange = useMemo(
    () => ({ date_range_start: startDate, date_range_end: scopeMode === "DAY" ? startDate : endDate }),
    [endDate, scopeMode, startDate],
  );
  const currentDraftQuery = useCurrentDraft(selectedRange);
  const generateMutation = useGenerateDraft();
  const approveMutation = useApproveDraft();
  const discardMutation = useDiscardDraft();
  const confirmDiscard = useUnsavedDraftGuard(isDirty);
  const persistedResultRef = useRef(persistedResult);
  const isDirtyRef = useRef(isDirty);

  useEffect(() => {
    persistedResultRef.current = persistedResult;
  }, [persistedResult]);

  useEffect(() => {
    isDirtyRef.current = isDirty;
  }, [isDirty]);

  useEffect(() => {
    if (currentDraftQuery.isLoading) return;
    if (isDirtyRef.current) {
      const remote = currentDraftQuery.data;
      const localBaseline = persistedResultRef.current;
      if (
        remote &&
        localBaseline &&
        (remote.draft_id !== localBaseline.draft_id || remote.state !== localBaseline.state)
      ) {
        setGenerateError({
          title: REVIEW_DRAFT_TEXTS.DRAFT_CHANGED_TITLE,
          detail: REVIEW_DRAFT_TEXTS.DRAFT_CHANGED_OTHER_TAB_DETAIL,
        });
      }
      return;
    }

    const remote = currentDraftQuery.data ?? null;
    setPersistedResult(remote);
    setDraft(remote?.draft ?? null);
    setVerification(remote?.verification ?? null);
    setSelectedIndex(null);
  }, [
    currentDraftQuery.data,
    currentDraftQuery.isLoading,
  ]);

  const currentQueryError = currentDraftQuery.isError && !queryErrorDismissed
    ? describeApiError(currentDraftQuery.error, "generate")
    : null;
  const displayedStartDate = persistedResult?.date_range_start ?? startDate;
  const displayedEndDate = persistedResult?.date_range_end ?? (scopeMode === "DAY" ? startDate : endDate);
  const displayedScopeMode = displayedStartDate === displayedEndDate ? "DAY" : "RANGE";

  const getSelectedDateRange = () => {
    const date_range_start = displayedStartDate > todayStr ? todayStr : displayedStartDate;
    const date_range_end = displayedEndDate > todayStr ? todayStr : displayedEndDate;
    return { date_range_start, date_range_end };
  };

  const handleGenerate = () => {
    if (!confirmDiscard()) return;
    setApproveSuccess(false);
    setSelectedIndex(null);
    setGenerateError(null);
    setQueryErrorDismissed(false);
    setApproveError(null);
    setDiscardError(null);
    setAddBlockError(null);
    generateMutation.mutate(
      {
        ...getSelectedDateRange(),
        ...(persistedResult?.state === "active" ? { replace_draft_id: persistedResult.draft_id } : {}),
      },
      {
        onSuccess: (data) => {
          setPersistedResult(data);
          setDraft(data.draft);
          setVerification(data.verification);
          setIsDirty(false);
        },
        onError: (error) => {
          setGenerateError(describeApiError(error, "generate"));
        },
      },
    );
  };

  const handleApprove = () => {
    if (!draft || !persistedResult || persistedResult.state !== "active") return;
    setApproveError(null);
    approveMutation.mutate({ ...getSelectedDateRange(), draft_id: persistedResult.draft_id, draft }, {
      onSuccess: () => {
        setPersistedResult({ ...persistedResult, state: "approved", draft });
        setIsDirty(false);
        setApproveSuccess(true);
        setSelectedIndex(null);
      },
      onError: (error) => {
        setApproveSuccess(false);
        setApproveError(describeApiError(error, "approve"));
      },
    });
  };

  const handleDiscard = () => {
    if (!persistedResult || persistedResult.state !== "active") return;
    setDiscardError(null);
    setConfirmDiscardOpen(true);
  };

  const confirmDiscardDraft = () => {
    if (!persistedResult) return;
    setConfirmDiscardOpen(false);
    discardMutation.mutate(persistedResult.draft_id, {
      onSuccess: () => {
        setPersistedResult(null);
        setDraft(null);
        setVerification(null);
        setIsDirty(false);
        setApproveSuccess(false);
        setSelectedIndex(null);
        setIgnoredGapDraftId(null);
        setAddBlockError(null);
      },
      onError: (error) => {
        setDiscardError(describeApiError(error, "discard"));
      },
    });
  };

  const updateEntry = (entryIndex: number, patch: Partial<DraftEntry>) => {
    if (!draft) return;
    setIsDirty(true);
    setApproveSuccess(false);
    setDraft({
      ...draft,
      entries: draft.entries.map((entry, idx) => (idx === entryIndex ? ({ ...entry, ...patch } as DraftEntry) : entry)),
    });
  };

  const updateEntryMinutes = (entryIndex: number, newMinutes: number) => {
    if (!draft) return;
    const entry = draft.entries[entryIndex];
    if (entry.origin === "manual" && entry.allocations.length === 0) {
      setDraft({
        ...draft,
        entries: draft.entries.map((candidate, idx) =>
          idx === entryIndex ? { ...entry, manual_minutes: Math.min(24 * 60, Math.max(1, newMinutes)) } : candidate,
        ),
      });
    } else {
      if (entry.allocations.length !== 1) return;
      const nextAllocations = [{ ...entry.allocations[0], minutes: Math.max(1, newMinutes) }];
      const nextResidual = rebalanceResidual(
        draft.residual_unassigned_minutes,
        entry.allocations,
        nextAllocations,
      );
      if (nextResidual === null) {
        setAddBlockError(TRACKED_TIME_ERROR);
        return;
      }
      setAddBlockError(null);
      setDraft({
        ...draft,
        entries: draft.entries.map((candidate, idx) =>
          idx === entryIndex ? ({ ...entry, allocations: nextAllocations } as DraftEntry) : candidate,
        ),
        residual_unassigned_minutes: nextResidual,
      });
    }
    setIsDirty(true);
    setApproveSuccess(false);
  };

  const deleteEntry = (entryIndex: number) => {
    if (!draft) return;
    const removed = draft.entries[entryIndex];
    const nextResidual = removed.allocations.length > 0
      ? rebalanceResidual(draft.residual_unassigned_minutes, removed.allocations, [])
      : draft.residual_unassigned_minutes;
    setIsDirty(true);
    setApproveSuccess(false);
    setDraft({
      ...draft,
      entries: draft.entries.filter((_, idx) => idx !== entryIndex),
      residual_unassigned_minutes: nextResidual ?? draft.residual_unassigned_minutes,
    });
    if (selectedIndex === entryIndex) setSelectedIndex(null);
    else if (selectedIndex !== null && selectedIndex > entryIndex) setSelectedIndex(selectedIndex - 1);
  };

  const addResidualEntry = () => {
    if (!draft) return;
    const available = draft.residual_unassigned_minutes.find((b) => b.minutes > 0);
    if (!available) {
      setAddBlockError({
        title: REVIEW_DRAFT_TEXTS.NO_UNTRACKED_TIME_TITLE,
        detail: REVIEW_DRAFT_TEXTS.NO_UNTRACKED_TIME_DETAIL,
      });
      return;
    }

    setAddBlockError(null);
    const assignedMinutes = Math.min(30, available.minutes);
    const newEntry: DraftEntry = {
      date: available.date ?? displayedStartDate,
      project: "unidentified",
      origin: "manual",
      allocations: [{ ...available, minutes: assignedMinutes }],
      tag: "Coding",
      description: "New workstream block",
      source_remote_event_ids: [],
    };
    setDraft({
      ...draft,
      entries: [...draft.entries, newEntry],
      residual_unassigned_minutes: draft.residual_unassigned_minutes.flatMap((allocation) => {
        if (allocation.block_id !== available.block_id) return [allocation];
        const remaining = allocation.minutes - assignedMinutes;
        return remaining > 0 ? [{ ...allocation, minutes: remaining }] : [];
      }),
    });
    setIsDirty(true);
    setApproveSuccess(false);
    setSelectedIndex(draft.entries.length);
  };

  const addManualEntry = () => {
    if (!draft) return;
    const newEntry: DraftEntry = {
      date: displayedStartDate,
      project: "unidentified",
      origin: "manual",
      allocations: [],
      manual_minutes: 30,
      tag: "Other",
      description: "New manual work block",
      source_remote_event_ids: [],
    };
    setDraft({ ...draft, entries: [...draft.entries, newEntry] });
    setAddBlockError(null);
    setIsDirty(true);
    setApproveSuccess(false);
    setSelectedIndex(draft.entries.length);
  };

  const commitScope = (nextStart: string, nextEnd: string, nextMode: "DAY" | "RANGE") => {
    if (!confirmDiscard()) return false;
    const boundedStart = nextStart > todayStr ? todayStr : nextStart;
    const boundedEnd = nextMode === "DAY" ? boundedStart : nextEnd > todayStr ? todayStr : nextEnd;
    const normalizedEnd = boundedEnd < boundedStart ? boundedStart : boundedEnd;
    const sameScope = boundedStart === displayedStartDate && normalizedEnd === displayedEndDate;
    const baseline = sameScope ? currentDraftQuery.data ?? persistedResult : null;
    setDraft(baseline?.draft ?? null);
    setPersistedResult(baseline);
    setVerification(baseline?.verification ?? null);
    setApproveSuccess(false);
    setSelectedIndex(null);
    setIsDirty(false);
    setGenerateError(null);
    setQueryErrorDismissed(false);
    setApproveError(null);
    setDiscardError(null);
    setStartDate(boundedStart);
    setEndDate(normalizedEnd);
    setScopeMode(nextMode);
    return true;
  };

  const shiftDate = (days: number) => {
    const anchor = displayedScopeMode === "RANGE" && days > 0 ? displayedEndDate : displayedStartDate;
    const curr = parseLocalDate(anchor);
    curr.setDate(curr.getDate() + days);
    const y = curr.getFullYear();
    const m = String(curr.getMonth() + 1).padStart(2, "0");
    const d = String(curr.getDate()).padStart(2, "0");
    const formatted = `${y}-${m}-${d}`;
    if (formatted > todayStr) return;
    commitScope(formatted, formatted, "DAY");
  };

  const applyPreset = (preset: "today" | "yesterday" | "this_week" | "last_week") => {
    const today = new Date();
    const formatDateStr = (date: Date) => {
      const y = date.getFullYear();
      const m = String(date.getMonth() + 1).padStart(2, "0");
      const d = String(date.getDate()).padStart(2, "0");
      return `${y}-${m}-${d}`;
    };

    if (preset === "today") {
      const str = formatDateStr(today);
      if (!commitScope(str, str, "DAY")) return;
    } else if (preset === "yesterday") {
      const y = new Date(today);
      y.setDate(y.getDate() - 1);
      const str = formatDateStr(y);
      if (!commitScope(str, str, "DAY")) return;
    } else if (preset === "this_week") {
      const monday = new Date(today);
      const dayOfWeek = monday.getDay() || 7;
      monday.setDate(monday.getDate() - dayOfWeek + 1);
      if (!commitScope(formatDateStr(monday), formatDateStr(today), "RANGE")) return;
    } else if (preset === "last_week") {
      const monday = new Date(today);
      const dayOfWeek = monday.getDay() || 7;
      monday.setDate(monday.getDate() - dayOfWeek - 6);
      const sunday = new Date(monday);
      sunday.setDate(sunday.getDate() + 6);
      if (!commitScope(formatDateStr(monday), formatDateStr(sunday), "RANGE")) return;
    }
    setPickerOpen(false);
  };

  const allocatedMins = draft
    ? draft.entries.reduce(
        (sum, entry) =>
          sum + (entry.origin === "manual" && entry.allocations.length === 0
            ? entry.manual_minutes ?? 0
            : entry.allocations.reduce((entrySum, allocation) => entrySum + allocation.minutes, 0)),
        0,
      )
    : 0;
  const trackedMins = draft ? draft.tracked_wall_clock_minutes : 0;
  const manualUntrackedMins = draft
    ? draft.entries.reduce(
        (sum, entry) => sum + (entry.origin === "manual" && entry.allocations.length === 0 ? entry.manual_minutes ?? 0 : 0),
        0,
      )
    : 0;
  const blocksCount = draft ? draft.entries.length : 0;
  const unaccountedMins = draft ? draft.residual_unassigned_minutes.reduce((sum, a) => sum + a.minutes, 0) : 0;

  const selectedEntry = selectedIndex !== null && draft?.entries[selectedIndex] ? draft.entries[selectedIndex] : null;
  const selectedMinutes = selectedEntry
    ? selectedEntry.origin === "manual" && selectedEntry.allocations.length === 0
      ? selectedEntry.manual_minutes ?? 0
      : selectedEntry.allocations.reduce((sum, a) => sum + a.minutes, 0)
    : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[#191917]">Review draft</h1>
          <p className="mt-1 text-sm text-[#6E6C62]">
            {draft
              ? persistedResult?.state === "approved"
                ? `${draft.entries.length} workstreams saved for this scope.`
                : `${draft.entries.length} workstreams synthesised from signals. Edit anything that reads wrong, then save the day.`
              : "Generate an AI-reconciled draft of your daily workstreams before saving."}
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generateMutation.isPending || persistedResult?.state === "approved"}
            className="rounded-md border border-[#CFCABA] bg-[#FFFDF7] px-3.5 py-2 text-sm font-medium text-[#191917] transition-colors hover:bg-[#F5F2EA] disabled:opacity-50"
          >
            {generateMutation.isPending ? "Reconciling..." : "Regenerate"}
          </button>
          {persistedResult?.state === "active" && (
            <button
              type="button"
              onClick={handleDiscard}
              disabled={discardMutation.isPending || approveMutation.isPending || generateMutation.isPending}
              className="rounded-md border border-[#D8B4B4] bg-[#FFFDF7] px-3.5 py-2 text-sm font-medium text-[#7A2E2E] transition-colors hover:bg-[#FBF0EF] disabled:opacity-50"
            >
              {discardMutation.isPending ? "Discarding..." : "Discard draft"}
            </button>
          )}
          <button
            type="button"
            onClick={handleApprove}
            disabled={!draft || !persistedResult || persistedResult.state !== "active" || approveMutation.isPending || approveSuccess}
            className="rounded-md border border-[#14603C] bg-[#14603C] px-4 py-2 text-sm font-semibold text-[#FFFDF7] shadow-sm transition-colors hover:bg-[#0F4E31] disabled:opacity-50"
          >
            {persistedResult?.state === "approved" || approveSuccess
              ? "Saved ✓"
              : approveMutation.isPending
                ? "Saving..."
                : "Save day"}
          </button>
        </div>
      </div>

      <div className="relative flex flex-wrap items-center rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] shadow-sm">
        <div className="flex items-center gap-1 border-r border-[#E3DFD2] p-2">
          <button
            type="button"
            onClick={() => shiftDate(-1)}
            aria-label="Previous day"
            className="flex h-7 w-7 items-center justify-center rounded-md text-sm text-[#57564E] transition-colors hover:border hover:border-[#E3DFD2] hover:bg-[#F5F2EA]"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => {
              setPendingStartDate(displayedStartDate);
              setPendingEndDate(displayedEndDate);
              setPickerOpen(!pickerOpen);
            }}
            className="flex items-center gap-2.5 rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-1.5 transition-colors hover:border-[#CFCABA]"
          >
            <span className="font-mono text-xs font-medium text-[#191917]">
              {displayedStartDate === todayStr ? `Today (${displayedStartDate})` : displayedStartDate}
              {displayedScopeMode === "RANGE" && ` to ${displayedEndDate}`}
            </span>
            <span className="font-mono text-[10px] text-[#8A887C]">▾</span>
          </button>
          <button
            type="button"
            onClick={() => shiftDate(1)}
            disabled={displayedEndDate >= todayStr}
            aria-label="Next day"
            className="flex h-7 w-7 items-center justify-center rounded-md text-sm text-[#57564E] transition-colors hover:border hover:border-[#E3DFD2] hover:bg-[#F5F2EA] disabled:opacity-30 disabled:pointer-events-none"
          >
            ›
          </button>
        </div>

        <div className="flex items-center border-r border-[#E3DFD2] p-2">
          <div className="flex gap-0.5 rounded-md bg-[#F1EDE2] p-0.5">
            <button
              type="button"
              onClick={() => commitScope(displayedStartDate, displayedStartDate, "DAY")}
              className={`rounded px-2.5 py-1 font-mono text-[11px] font-semibold transition-colors ${
                displayedScopeMode === "DAY" ? "bg-[#FFFDF7] text-[#14603C] shadow-xs" : "text-[#8A887C]"
              }`}
            >
              DAY
            </button>
            <button
              type="button"
              onClick={() => commitScope(displayedStartDate, displayedEndDate, "RANGE")}
              className={`rounded px-2.5 py-1 font-mono text-[11px] font-semibold transition-colors ${
                displayedScopeMode === "RANGE" ? "bg-[#FFFDF7] text-[#14603C] shadow-xs" : "text-[#8A887C]"
              }`}
            >
              RANGE
            </button>
          </div>
        </div>

        <div className="flex flex-1 items-center justify-around gap-4 px-4 py-2">
          <div className="flex flex-col">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C]">TRACKED</span>
            <span className="font-mono text-sm font-medium text-[#191917]">{formatMinutes(trackedMins)}</span>
          </div>
          <div className="flex flex-col">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C]">ALLOCATED</span>
            <span
              className="font-mono text-sm font-medium text-[#191917]"
              title={
                allocatedMins > trackedMins
                  ? manualUntrackedMins > 0
                    ? "Includes work added manually because it was not observed by the tracker."
                    : "Exceeds tracked time because concurrent work, such as a meeting running alongside other activity, is allocated to more than one entry."
                  : undefined
              }
            >
              {formatMinutes(allocatedMins)}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C]">BLOCKS</span>
            <span className="font-mono text-sm font-medium text-[#191917]">{blocksCount}</span>
          </div>
          <div className="flex flex-col">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C]">UNACCOUNTED</span>
            <span className="font-mono text-sm font-medium text-[#6E6C62]">{formatMinutes(unaccountedMins)}</span>
          </div>
        </div>

        {pickerOpen && (
          <>
            <button type="button" aria-label="Close date picker" className="fixed inset-0 z-30 cursor-default" onClick={() => setPickerOpen(false)} />
            <div className="absolute left-2 top-full z-40 mt-1.5 flex rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] shadow-elevated">
              <div className="flex flex-col gap-1 border-r border-[#E3DFD2] p-3 w-40">
                <span className="font-mono text-[10px] tracking-wider text-[#8A887C] px-2 py-1">PRESETS</span>
                <button
                  type="button"
                  onClick={() => applyPreset("today")}
                  className="rounded px-2.5 py-1.5 text-left text-xs font-medium text-[#191917] hover:bg-[#F5F2EA]"
                >
                  Today
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset("yesterday")}
                  className="rounded px-2.5 py-1.5 text-left text-xs font-medium text-[#191917] hover:bg-[#F5F2EA]"
                >
                  Yesterday
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset("this_week")}
                  className="rounded px-2.5 py-1.5 text-left text-xs font-medium text-[#191917] hover:bg-[#F5F2EA]"
                >
                  This week
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset("last_week")}
                  className="rounded px-2.5 py-1.5 text-left text-xs font-medium text-[#191917] hover:bg-[#F5F2EA]"
                >
                  Last week
                </button>
              </div>

              <div className="p-4 space-y-3">
                <span className="font-mono text-[10px] tracking-wider text-[#8A887C] block">CUSTOM DATES</span>
                <div className="flex items-center gap-2 font-mono text-xs">
                  <input
                    type="date"
                    max={todayStr}
                    value={pendingStartDate}
                    onChange={(e) => {
                      const val = e.target.value;
                      setPendingStartDate(val > todayStr ? todayStr : val);
                    }}
                    className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2.5 py-1.5 text-[#191917] focus:border-[#14603C] focus:outline-none"
                  />
                  <span className="text-[#8A887C]">to</span>
                  <input
                    type="date"
                    max={todayStr}
                    value={pendingEndDate}
                    onChange={(e) => {
                      const val = e.target.value;
                      setPendingEndDate(val > todayStr ? todayStr : val);
                    }}
                    className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2.5 py-1.5 text-[#191917] focus:border-[#14603C] focus:outline-none"
                  />
                </div>
                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (commitScope(pendingStartDate, pendingEndDate, displayedScopeMode)) {
                        setPickerOpen(false);
                      }
                    }}
                    className="rounded bg-[#14603C] px-3.5 py-1.5 text-xs font-semibold text-[#FFFDF7] hover:bg-[#0F4E31]"
                  >
                    Apply
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {(generateError || currentQueryError) && (
        <ErrorBanner
          error={generateError ?? currentQueryError!}
          onDismiss={() => {
            setGenerateError(null);
            setQueryErrorDismissed(true);
          }}
        />
      )}
      {approveError && <ErrorBanner error={approveError} onDismiss={() => setApproveError(null)} />}
      {discardError && <ErrorBanner error={discardError} onDismiss={() => setDiscardError(null)} />}
      {addBlockError && <ErrorBanner error={addBlockError} onDismiss={() => setAddBlockError(null)} />}

      <ConfirmDialog
        open={confirmDiscardOpen}
        title={REVIEW_DRAFT_TEXTS.DISCARD_DRAFT_TITLE}
        message={REVIEW_DRAFT_TEXTS.DISCARD_DRAFT_PROMPT}
        confirmLabel={REVIEW_DRAFT_TEXTS.DISCARD_DRAFT_CONFIRM_LABEL}
        working={discardMutation.isPending}
        workingLabel={REVIEW_DRAFT_TEXTS.DISCARD_DRAFT_WORKING_LABEL}
        onConfirm={confirmDiscardDraft}
        onCancel={() => setConfirmDiscardOpen(false)}
      />

      {verification && !verification.passed && (
        <div
          role="status"
          className="mb-4 rounded-md border border-[#E4CFA3] bg-[#F7EDD8] px-4 py-3 text-[#8A5A0F]"
        >
          <p className="text-sm font-semibold">This draft did not pass the evidence checks</p>
          <p className="mt-1 text-xs leading-relaxed">
            Review the entries below before saving — the server will reject the save while these remain.
          </p>
          <ul className="mt-2 space-y-1 text-xs">
            {verification.issues.map((issue, idx) => (
              <li key={`${issue.check}-${idx}`} className="font-mono">
                [{issue.severity}] {issue.check}
                {issue.block_id != null ? ` (block ${issue.block_id})` : ""}
                {issue.entry_index != null ? ` (entry ${issue.entry_index + 1})` : ""} — {issue.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {approveSuccess && (
        <div className="flex items-center justify-between rounded-lg border border-[#BFD9C2] bg-[#DCEBDD] p-4 text-sm font-semibold text-[#14603C]">
          <span>✓ Draft entries successfully approved and saved!</span>
          <button
            type="button"
            onClick={() => navigate("/compose")}
            className="rounded bg-[#14603C] px-3 py-1 text-xs font-semibold text-[#FFFDF7] hover:bg-[#0F4E31]"
          >
            Compose standup →
          </button>
        </div>
      )}

      {(generateMutation.isPending || (currentDraftQuery.isLoading && !draft)) && (
        <div className="rounded-xl border border-[#E3DFD2] bg-[#FFFDF7] p-12 text-center shadow-sm space-y-4">
          <div className="flex justify-center">
            <Loading size="lg" />
          </div>
          <h3 className="font-mono text-lg font-bold text-[#191917]">Analyzing Activity & Remote Evidence...</h3>
          <p className="text-sm text-[#6E6C62] max-w-md mx-auto">
            Logline is aggregating local activity logs and remote signals to synthesize workstream entries.
          </p>
        </div>
      )}

      {!draft && !generateMutation.isPending && !currentDraftQuery.isLoading && (
        <div className="rounded-xl border border-dashed border-[#CFCABA] bg-[#FFFDF7]/50 p-12 text-center">
          <p className="text-[#6E6C62]">No draft loaded. Click &quot;Regenerate&quot; or pick a date range to generate a draft.</p>
        </div>
      )}

      {draft && (
        <div className="flex gap-6 items-start">
          <div className="flex-1 min-w-0 space-y-3">
            {draft.entries.map((entry, idx) => {
              const entryMins = entry.origin === "manual" && entry.allocations.length === 0
                ? entry.manual_minutes ?? 0
                : entry.allocations.reduce((sum, a) => sum + a.minutes, 0);
              const isSelected = selectedIndex === idx;

              return (
                <div
                  key={entry.entry_id ?? `${entry.date}-${entry.project}-${entry.description.slice(0, 20)}-${idx}`}
                  className={`flex rounded-lg border bg-[#FFFDF7] transition-all ${
                    isSelected
                      ? "border-[#14603C] ring-2 ring-[#14603C]/20 shadow-md"
                      : "border-[#E3DFD2] hover:border-[#CFCABA]"
                  }`}
                >
                  <div className="w-1 rounded-l-lg bg-[#14603C]" />
                  <div className="flex-1 p-4">
                    <div className="flex items-baseline gap-3">
                      <span className="font-mono text-sm font-medium text-[#191917]">{formatMinutes(entryMins)}</span>
                      <span className="font-mono text-xs text-[#8A887C]">
                        {(entry.source_remote_event_ids?.length ?? 0) > 0
                          ? `${entry.source_remote_event_ids?.length} remote signals`
                          : entry.origin === "manual"
                            ? "manual time"
                            : "local activity"}
                      </span>
                    </div>

                    <p className="mt-2 text-sm text-[#191917] leading-relaxed">{entry.description}</p>

                    {entry.review_reason && (
                      <p className="mt-1.5 text-xs text-[#8A5A0F] leading-snug">{entry.review_reason}</p>
                    )}

                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2 py-0.5 text-xs text-[#57564E]">
                          {entry.tag}
                        </span>
                      </div>

                      {persistedResult?.state === "active" && <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setSelectedIndex(isSelected ? null : idx)}
                          className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                            isSelected
                              ? "bg-[#14603C] text-[#FFFDF7]"
                              : "border border-[#E3DFD2] bg-[#FFFDF7] text-[#191917] hover:bg-[#F5F2EA]"
                          }`}
                        >
                          {isSelected ? "Editing" : "Edit"}
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteEntry(idx)}
                          className="text-xs text-[#8A887C] hover:text-[#A33A22]"
                        >
                          Discard
                        </button>
                      </div>}
                    </div>
                  </div>
                </div>
              );
            })}

            {persistedResult?.state === "active" && unaccountedMins > 0 && ignoredGapDraftId !== persistedResult.draft_id && (
              <div className="flex items-center justify-between gap-4 rounded-lg border border-dashed border-[#CFCABA] p-3 text-xs">
                <span className="font-mono text-[#6E6C62]">{formatMinutes(unaccountedMins)} unaccounted</span>
                <span className="font-mono text-[#8A887C]">Unassigned activity observed by local tracker</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={addResidualEntry}
                    className="rounded border border-[#CFCABA] bg-[#FFFDF7] px-2.5 py-1 font-medium text-[#191917] hover:bg-[#F5F2EA]"
                  >
                    Add a block
                  </button>
                  <button
                    type="button"
                    onClick={() => setIgnoredGapDraftId(persistedResult.draft_id)}
                    className="text-[#8A887C] hover:text-[#191917]"
                  >
                    Ignore
                  </button>
                </div>
              </div>
            )}

            {persistedResult?.state === "active" && (
              <button
                type="button"
                onClick={addManualEntry}
                className="w-full rounded-lg border border-dashed border-[#CFCABA] p-3 text-left text-xs text-[#6E6C62] transition-colors hover:border-[#14603C] hover:text-[#14603C]"
              >
                + Add a block the tracker missed
              </button>
            )}
          </div>

          {persistedResult?.state === "active" && selectedEntry !== null && selectedIndex !== null && (
            <aside className="w-80 flex-none rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] shadow-sm space-y-4 p-4 sticky top-6">
              <div className="flex items-center justify-between border-b border-[#E3DFD2] pb-3">
                <span className="font-mono text-xs tracking-wider text-[#8A887C]">EDITING · blk-{selectedIndex + 1}</span>
                <button
                  type="button"
                  onClick={() => setSelectedIndex(null)}
                  className="text-[#8A887C] hover:text-[#191917]"
                >
                  ✕
                </button>
              </div>

              <div className="space-y-1.5">
                <label className="font-mono text-[10px] tracking-wider text-[#8A887C] block">DESCRIPTION</label>
                <textarea
                  rows={4}
                  value={selectedEntry.description}
                  onChange={(e) => updateEntry(selectedIndex, { description: e.target.value })}
                  className="w-full rounded border border-[#E3DFD2] bg-[#FFFDF7] p-2.5 text-xs text-[#191917] focus:border-[#14603C] focus:outline-none"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-mono text-[10px] tracking-wider text-[#8A887C] block">TIME SPENT</label>
                {selectedEntry.allocations.length > 1 && (
                  <p className="text-[11px] text-[#8A887C]">
                    This entry spans multiple measured blocks, so its time must stay tied to those source blocks.
                  </p>
                )}
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="0"
                    disabled={selectedEntry.allocations.length > 1}
                    value={Math.floor(selectedMinutes / 60)}
                    onChange={(e) => {
                      const h = parseInt(e.target.value, 10) || 0;
                      const m = selectedMinutes % 60;
                      updateEntryMinutes(selectedIndex, h * 60 + m);
                    }}
                    className="w-12 rounded border border-[#E3DFD2] bg-[#FFFDF7] py-1 text-center font-mono text-xs text-[#191917] focus:border-[#14603C] focus:outline-none"
                  />
                  <span className="font-mono text-xs text-[#8A887C]">h</span>
                  <input
                    type="number"
                    min="0"
                    max="59"
                    disabled={selectedEntry.allocations.length > 1}
                    value={selectedMinutes % 60}
                    onChange={(e) => {
                      const m = parseInt(e.target.value, 10) || 0;
                      const h = Math.floor(selectedMinutes / 60);
                      updateEntryMinutes(selectedIndex, h * 60 + m);
                    }}
                    className="w-12 rounded border border-[#E3DFD2] bg-[#FFFDF7] py-1 text-center font-mono text-xs text-[#191917] focus:border-[#14603C] focus:outline-none"
                  />
                  <span className="font-mono text-xs text-[#8A887C]">m</span>
                </div>

                <div className="flex items-center gap-1 pt-1 flex-wrap">
                  {[15, 30, 60, 120, 240].map((mins) => (
                    <button
                      key={mins}
                      type="button"
                      disabled={selectedEntry.allocations.length > 1}
                      onClick={() => updateEntryMinutes(selectedIndex, mins)}
                      className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2 py-0.5 font-mono text-[11px] text-[#57564E] hover:border-[#CFCABA] disabled:opacity-40"
                    >
                      {formatMinutes(mins)}
                    </button>
                  ))}
                </div>
              </div>

              {displayedScopeMode === "RANGE" && selectedEntry.origin === "manual" && selectedEntry.allocations.length === 0 && (
                <div className="space-y-1.5">
                  <label className="font-mono text-[10px] tracking-wider text-[#8A887C] block">WORK DATE</label>
                  <input
                    type="date"
                    aria-label="Work date"
                    min={displayedStartDate}
                    max={displayedEndDate}
                    value={selectedEntry.date}
                    onChange={(event) => updateEntry(selectedIndex, { date: event.target.value })}
                    className="w-full rounded border border-[#E3DFD2] bg-[#FFFDF7] px-2.5 py-1.5 font-mono text-xs text-[#191917] focus:border-[#14603C] focus:outline-none"
                  />
                </div>
              )}

              <div className="space-y-1.5">
                <label className="font-mono text-[10px] tracking-wider text-[#8A887C] block">TAG</label>
                <TagSelect
                  value={selectedEntry.tag}
                  onChange={(nextTag) => updateEntry(selectedIndex, { tag: nextTag })}
                />
              </div>

              <div className="space-y-2 border-t border-[#E3DFD2] pt-3">
                <label className="font-mono text-[10px] tracking-wider text-[#8A887C] block">
                  WHY THIS BLOCK EXISTS
                </label>
                <div className="space-y-1.5 text-xs text-[#6E6C62]">
                  {selectedEntry.review_reason && (
                    <div className="rounded bg-[#F7EDD8] p-2 space-y-1 border border-[#E4CFA3]">
                      <div className="flex justify-between font-mono text-[10px] text-[#8A5A0F]">
                        <span>REVIEW NOTE</span>
                      </div>
                      <p className="text-[11px] text-[#191917]">{selectedEntry.review_reason}</p>
                    </div>
                  )}

                  {selectedEntry.allocations.length > 0 && (
                    <div className="rounded bg-[#F5F2EA] p-2 space-y-1 border border-[#E3DFD2]">
                      <div className="flex justify-between font-mono text-[10px] text-[#8A887C]">
                        <span>LOCAL ACTIVITY</span>
                        <span>
                          {formatMinutes(selectedEntry.allocations.reduce((sum, a) => sum + a.minutes, 0))}
                        </span>
                      </div>
                      <p className="text-[11px] text-[#191917]">
                        {selectedEntry.allocations.length === 1
                          ? `1 measured block, ${formatMinutes(selectedEntry.allocations[0].minutes)}`
                          : `${selectedEntry.allocations.length} measured blocks totaling ${formatMinutes(
                              selectedEntry.allocations.reduce((sum, a) => sum + a.minutes, 0),
                            )}`}
                      </p>
                    </div>
                  )}

                  {selectedEntry.source_remote_event_ids && selectedEntry.source_remote_event_ids.length > 0 && (
                    <div className="rounded bg-[#F5F2EA] p-2 space-y-1 border border-[#E3DFD2]">
                      <div className="flex justify-between font-mono text-[10px] text-[#8A887C]">
                        <span>REMOTE SIGNALS</span>
                        <span>{selectedEntry.source_remote_event_ids.length}</span>
                      </div>
                      <p className="text-[11px] text-[#191917]">
                        {selectedEntry.source_remote_event_ids.length === 1
                          ? "1 linked event (PR, commit, or ticket)"
                          : `${selectedEntry.source_remote_event_ids.length} linked events (PRs, commits, or tickets)`}
                      </p>
                    </div>
                  )}

                  {selectedEntry.allocations.length === 0 &&
                    (!selectedEntry.source_remote_event_ids || selectedEntry.source_remote_event_ids.length === 0) && (
                      <div className="rounded bg-[#F5F2EA] p-2 space-y-1 border border-[#E3DFD2]">
                        <p className="text-[11px] text-[#8A887C]">
                          No telemetry signals — this block was added manually.
                        </p>
                      </div>
                    )}
                </div>
              </div>

              <div className="flex items-center gap-2 border-t border-[#E3DFD2] pt-3">
                <button
                  type="button"
                  onClick={() => setSelectedIndex(null)}
                  className="flex-1 rounded bg-[#14603C] py-2 text-xs font-semibold text-[#FFFDF7] hover:bg-[#0F4E31]"
                >
                  Save changes
                </button>
                <button
                  type="button"
                  onClick={() => deleteEntry(selectedIndex)}
                  className="rounded border border-[#E3DFD2] bg-[#FFFDF7] px-3 py-2 text-xs text-[#8A887C] hover:text-[#A33A22]"
                >
                  Discard
                </button>
              </div>
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
