import { useEffect, useMemo, useRef, useState } from "react";
import { Loading } from "@/atoms";
import { formatMinutes, getTodayLocalDate, parseLocalDate } from "@/common/utils";
import { ApiError } from "@/repositories/api";
import { ALL_ENTRY_TAGS, type DraftEntry, type EntryTag, type ReconciliationResult, type VerificationIssue, type WorkLogDraft } from "@/repositories/types";
import { useApproveDraft, useGenerateDraft } from "@/repositories/hooks";

export interface DescribedError {
  title: string;
  detail: string;
  issues?: VerificationIssue[];
}

const ACTION_LABEL: Record<"generate" | "approve", string> = {
  generate: "Could not generate a draft",
  approve: "Could not save the day",
};

function describeUnprocessable(body: unknown, fallbackTitle: string): DescribedError {
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "object" && detail !== null && "issues" in detail) {
    const { message, issues } = detail as { message?: string; issues?: VerificationIssue[] };
    return {
      title: "Draft rejected by the server's checks",
      detail: message ?? "The draft did not match the evidence it was generated from, so nothing was saved.",
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
      detail: messages.length ? `The server rejected this request — ${messages.join("; ")}` : "The server rejected this request as invalid.",
    };
  }

  return {
    title: fallbackTitle,
    detail: typeof detail === "string" ? detail : "The server rejected this request as invalid.",
  };
}

export function describeApiError(error: unknown, action: "generate" | "approve"): DescribedError {
  const fallbackTitle = ACTION_LABEL[action];

  if (error instanceof ApiError) {
    if (error.status === 404) {
      return {
        title: "This feature isn't available on the server",
        detail:
          "The backend has no /reconciliation endpoint. It is probably running a build from before " +
          "reconciliation was added — restart it from the current branch and try again.",
      };
    }
    if (error.status === 401) {
      return { title: "Your session has expired", detail: "Sign in again to keep going. Nothing was saved." };
    }
    if (error.status === 422) {
      return describeUnprocessable(error.body, fallbackTitle);
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
    title: "Could not reach the server",
    detail:
      "The request never completed. Check that the backend is running and reachable, then try again. " +
      "Nothing was saved.",
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
  const todayStr = useMemo(() => getTodayLocalDate(), []);
  const [startDate, setStartDate] = useState(getTodayLocalDate);
  const [endDate, setEndDate] = useState(getTodayLocalDate);
  const [scopeMode, setScopeMode] = useState<"DAY" | "RANGE">("DAY");
  const [pickerOpen, setPickerOpen] = useState(false);

  const [draft, setDraft] = useState<WorkLogDraft | null>(null);
  const [verification, setVerification] = useState<ReconciliationResult["verification"] | null>(null);
  const [approveSuccess, setApproveSuccess] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [ignoredGaps, setIgnoredGaps] = useState<Set<string>>(new Set());
  const [generateError, setGenerateError] = useState<DescribedError | null>(null);
  const [approveError, setApproveError] = useState<DescribedError | null>(null);

  const generateMutation = useGenerateDraft();
  const approveMutation = useApproveDraft();

  const handleGenerate = () => {
    setApproveSuccess(false);
    setSelectedIndex(null);
    setGenerateError(null);
    setApproveError(null);
    const effectiveStart = startDate > todayStr ? todayStr : startDate;
    const effectiveEnd = scopeMode === "DAY" ? effectiveStart : endDate > todayStr ? todayStr : endDate;
    generateMutation.mutate(
      { date_range_start: effectiveStart, date_range_end: effectiveEnd },
      {
        onSuccess: (data) => {
          setDraft(data.draft);
          setVerification(data.verification);
        },
        onError: (error) => {
          setGenerateError(describeApiError(error, "generate"));
        },
      },
    );
  };

  const handleApprove = () => {
    if (!draft) return;
    setApproveError(null);
    approveMutation.mutate(draft, {
      onSuccess: () => {
        setApproveSuccess(true);
      },
      onError: (error) => {
        setApproveSuccess(false);
        setApproveError(describeApiError(error, "approve"));
      },
    });
  };

  const updateEntry = (entryIndex: number, patch: Partial<DraftEntry>) => {
    if (!draft) return;
    setDraft({
      ...draft,
      entries: draft.entries.map((entry, idx) => (idx === entryIndex ? { ...entry, ...patch } : entry)),
    });
  };

  const updateEntryMinutes = (entryIndex: number, newMinutes: number) => {
    if (!draft) return;
    setDraft({
      ...draft,
      entries: draft.entries.map((entry, idx) => {
        if (idx !== entryIndex) return entry;
        const currentTotal = entry.allocations.reduce((sum, a) => sum + a.minutes, 0);

        if (entry.allocations.length === 0) {
          const available = draft.residual_unassigned_minutes.find((b) => b.minutes > 0);
          if (!available) return entry;
          return { ...entry, allocations: [{ block_id: available.block_id, minutes: newMinutes }] };
        }

        if (entry.allocations.length === 1) {
          return { ...entry, allocations: [{ ...entry.allocations[0], minutes: newMinutes }] };
        }

        const scale = currentTotal > 0 ? newMinutes / currentTotal : 0;
        const scaled = entry.allocations.map((a) => ({ ...a, minutes: Math.round(a.minutes * scale) }));
        const drift = newMinutes - scaled.reduce((s, a) => s + a.minutes, 0);
        scaled[0] = { ...scaled[0], minutes: Math.max(0, scaled[0].minutes + drift) };
        return { ...entry, allocations: scaled };
      }),
    });
  };

  const deleteEntry = (entryIndex: number) => {
    if (!draft) return;
    setDraft({
      ...draft,
      entries: draft.entries.filter((_, idx) => idx !== entryIndex),
    });
    if (selectedIndex === entryIndex) setSelectedIndex(null);
  };

  const addBlankEntry = () => {
    if (!draft) return;
    const available = draft.residual_unassigned_minutes.find((b) => b.minutes > 0);
    if (!available) return;

    const newEntry: DraftEntry = {
      date: startDate,
      project: "unidentified",
      allocations: [{ block_id: available.block_id, minutes: Math.min(30, available.minutes) }],
      tag: "Coding",
      description: "New workstream block",
      source_remote_event_ids: [],
    };
    setDraft({
      ...draft,
      entries: [...draft.entries, newEntry],
    });
    setSelectedIndex(draft.entries.length);
  };

  const shiftDate = (days: number) => {
    const curr = parseLocalDate(startDate);
    curr.setDate(curr.getDate() + days);
    const y = curr.getFullYear();
    const m = String(curr.getMonth() + 1).padStart(2, "0");
    const d = String(curr.getDate()).padStart(2, "0");
    const formatted = `${y}-${m}-${d}`;
    if (formatted > todayStr) return;
    setStartDate(formatted);
    setEndDate(formatted);
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
      setStartDate(str);
      setEndDate(str);
      setScopeMode("DAY");
    } else if (preset === "yesterday") {
      const y = new Date(today);
      y.setDate(y.getDate() - 1);
      const str = formatDateStr(y);
      setStartDate(str);
      setEndDate(str);
      setScopeMode("DAY");
    } else if (preset === "this_week") {
      const monday = new Date(today);
      const dayOfWeek = monday.getDay() || 7;
      monday.setDate(monday.getDate() - dayOfWeek + 1);
      setStartDate(formatDateStr(monday));
      setEndDate(formatDateStr(today));
      setScopeMode("RANGE");
    } else if (preset === "last_week") {
      const monday = new Date(today);
      const dayOfWeek = monday.getDay() || 7;
      monday.setDate(monday.getDate() - dayOfWeek - 6);
      const sunday = new Date(monday);
      sunday.setDate(sunday.getDate() + 6);
      setStartDate(formatDateStr(monday));
      setEndDate(formatDateStr(sunday));
      setScopeMode("RANGE");
    }
    setPickerOpen(false);
  };

  const allocatedMins = draft
    ? draft.entries.reduce((sum, e) => sum + e.allocations.reduce((aSum, a) => aSum + a.minutes, 0), 0)
    : 0;
  const trackedMins = draft ? draft.tracked_wall_clock_minutes : 0;
  const blocksCount = draft ? draft.entries.length : 0;
  const unaccountedMins = draft ? draft.residual_unassigned_minutes.reduce((sum, a) => sum + a.minutes, 0) : 0;

  const selectedEntry = selectedIndex !== null && draft?.entries[selectedIndex] ? draft.entries[selectedIndex] : null;
  const selectedMinutes = selectedEntry ? selectedEntry.allocations.reduce((sum, a) => sum + a.minutes, 0) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[#191917]">Review draft</h1>
          <p className="mt-1 text-sm text-[#6E6C62]">
            {draft
              ? `${draft.entries.length} workstreams synthesised from signals. Edit anything that reads wrong, then save the day.`
              : "Generate an AI-reconciled draft of your daily workstreams before saving."}
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generateMutation.isPending}
            className="rounded-md border border-[#CFCABA] bg-[#FFFDF7] px-3.5 py-2 text-sm font-medium text-[#191917] transition-colors hover:bg-[#F5F2EA] disabled:opacity-50"
          >
            {generateMutation.isPending ? "Reconciling..." : "Regenerate"}
          </button>
          <button
            type="button"
            onClick={handleApprove}
            disabled={!draft || approveMutation.isPending || approveSuccess || !draft.entries.length}
            className="rounded-md border border-[#14603C] bg-[#14603C] px-4 py-2 text-sm font-semibold text-[#FFFDF7] shadow-sm transition-colors hover:bg-[#0F4E31] disabled:opacity-50"
          >
            {approveSuccess ? "Saved ✓" : approveMutation.isPending ? "Saving..." : "Save day"}
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
            onClick={() => setPickerOpen(!pickerOpen)}
            className="flex items-center gap-2.5 rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-1.5 transition-colors hover:border-[#CFCABA]"
          >
            <span className="font-mono text-xs font-medium text-[#191917]">
              {startDate === todayStr ? `Today (${startDate})` : startDate}
              {scopeMode === "RANGE" && ` to ${endDate}`}
            </span>
            <span className="font-mono text-[10px] text-[#8A887C]">▾</span>
          </button>
          <button
            type="button"
            onClick={() => shiftDate(1)}
            disabled={startDate >= todayStr}
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
              onClick={() => setScopeMode("DAY")}
              className={`rounded px-2.5 py-1 font-mono text-[11px] font-semibold transition-colors ${
                scopeMode === "DAY" ? "bg-[#FFFDF7] text-[#14603C] shadow-xs" : "text-[#8A887C]"
              }`}
            >
              DAY
            </button>
            <button
              type="button"
              onClick={() => setScopeMode("RANGE")}
              className={`rounded px-2.5 py-1 font-mono text-[11px] font-semibold transition-colors ${
                scopeMode === "RANGE" ? "bg-[#FFFDF7] text-[#14603C] shadow-xs" : "text-[#8A887C]"
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
                  ? "Exceeds tracked time because concurrent work, such as a meeting running alongside other activity, is allocated to more than one entry."
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
                    value={startDate}
                    onChange={(e) => {
                      const val = e.target.value;
                      setStartDate(val > todayStr ? todayStr : val);
                    }}
                    className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2.5 py-1.5 text-[#191917] focus:border-[#14603C] focus:outline-none"
                  />
                  <span className="text-[#8A887C]">to</span>
                  <input
                    type="date"
                    max={todayStr}
                    value={endDate}
                    onChange={(e) => {
                      const val = e.target.value;
                      setEndDate(val > todayStr ? todayStr : val);
                    }}
                    className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2.5 py-1.5 text-[#191917] focus:border-[#14603C] focus:outline-none"
                  />
                </div>
                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setPickerOpen(false);
                      handleGenerate();
                    }}
                    className="rounded bg-[#14603C] px-3.5 py-1.5 text-xs font-semibold text-[#FFFDF7] hover:bg-[#0F4E31]"
                  >
                    Apply & Reconcile
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {generateError && <ErrorBanner error={generateError} onDismiss={() => setGenerateError(null)} />}
      {approveError && <ErrorBanner error={approveError} onDismiss={() => setApproveError(null)} />}

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
        </div>
      )}

      {generateMutation.isPending && (
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

      {!draft && !generateMutation.isPending && (
        <div className="rounded-xl border border-dashed border-[#CFCABA] bg-[#FFFDF7]/50 p-12 text-center">
          <p className="text-[#6E6C62]">No draft loaded. Click &quot;Regenerate&quot; or pick a date range to generate a draft.</p>
        </div>
      )}

      {draft && (
        <div className="flex gap-6 items-start">
          <div className="flex-1 min-w-0 space-y-3">
            {draft.entries.map((entry, idx) => {
              const entryMins = entry.allocations.reduce((sum, a) => sum + a.minutes, 0);
              const isSelected = selectedIndex === idx;

              return (
                <div
                  key={`${entry.date}-${entry.project}-${entry.description.slice(0, 20)}-${idx}`}
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

                      <div className="flex items-center gap-2">
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
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}

            {unaccountedMins > 0 && !ignoredGaps.has("main") && (
              <div className="flex items-center justify-between gap-4 rounded-lg border border-dashed border-[#CFCABA] p-3 text-xs">
                <span className="font-mono text-[#6E6C62]">{formatMinutes(unaccountedMins)} unaccounted</span>
                <span className="font-mono text-[#8A887C]">Unassigned activity observed by local tracker</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={addBlankEntry}
                    className="rounded border border-[#CFCABA] bg-[#FFFDF7] px-2.5 py-1 font-medium text-[#191917] hover:bg-[#F5F2EA]"
                  >
                    Add a block
                  </button>
                  <button
                    type="button"
                    onClick={() => setIgnoredGaps(new Set(ignoredGaps).add("main"))}
                    className="text-[#8A887C] hover:text-[#191917]"
                  >
                    Ignore
                  </button>
                </div>
              </div>
            )}

            <button
              type="button"
              onClick={addBlankEntry}
              className="w-full rounded-lg border border-dashed border-[#CFCABA] p-3 text-left text-xs text-[#6E6C62] transition-colors hover:border-[#14603C] hover:text-[#14603C]"
            >
              + Add a block the tracker missed
            </button>
          </div>

          {selectedEntry !== null && selectedIndex !== null && (
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
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="0"
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
                      onClick={() => updateEntryMinutes(selectedIndex, mins)}
                      className="rounded border border-[#E3DFD2] bg-[#F5F2EA] px-2 py-0.5 font-mono text-[11px] text-[#57564E] hover:border-[#CFCABA]"
                    >
                      {formatMinutes(mins)}
                    </button>
                  ))}
                </div>
              </div>

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
