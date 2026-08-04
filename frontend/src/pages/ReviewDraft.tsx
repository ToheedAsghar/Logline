import { useEffect, useRef, useState } from "react";
import { Button, Loading, Tooltip } from "@/atoms";
import { ALL_ENTRY_TAGS, type DraftEntry, type DraftReminder, type EntryTag, type ReconciliationResult, type WorkLogDraft } from "@/repositories/types";
import { useApproveDraft, useGenerateDraft } from "@/repositories/hooks";

/** Get current local date formatted as YYYY-MM-DD. */
export function getTodayLocalDate(): string {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Format minutes into human-readable "Xh Ym" string (e.g., 474 -> "7h 54m"). */
export function formatMinutes(totalMinutes: number): string {
  if (totalMinutes <= 0) return "0m";
  const hours = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;
  if (hours === 0) return `${mins}m`;
  if (mins === 0) return `${hours}h`;
  return `${hours}h ${mins}m`;
}

/** Convert total minutes into "HH:MM" string format. */
export function minutesToHHMM(totalMinutes: number): string {
  const h = Math.floor(Math.max(0, totalMinutes) / 60);
  const m = Math.max(0, totalMinutes) % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Parse HH:MM string or plain number into total minutes. */
export function parseTimeToMinutes(value: string): number {
  const trimmed = value.trim();
  if (!trimmed) return 0;

  if (trimmed.includes(":")) {
    const parts = trimmed.split(":");
    const h = parseInt(parts[0], 10) || 0;
    const m = parseInt(parts[1], 10) || 0;
    return Math.max(0, h * 60 + m);
  }

  const num = parseFloat(trimmed);
  if (isNaN(num)) return 0;
  if (num > 0 && num < 12 && trimmed.includes(".")) {
    return Math.round(num * 60);
  }
  return Math.round(num);
}

/** Custom scrollable & filterable dropdown for 36 EntryTag values. */
export function TagSelect({
  value,
  onChange,
}: {
  value: EntryTag;
  onChange: (tag: EntryTag) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [openUpward, setOpenUpward] = useState(false);
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

  const toggleOpen = () => {
    if (!open && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      setOpenUpward(spaceBelow < 250);
    }
    setOpen(!open);
  };

  return (
    <div className="relative inline-block w-full">
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        aria-label="Entry tag selector"
        aria-expanded={open}
        role="combobox"
        className="flex w-full items-center justify-between gap-1 rounded border border-border bg-bg px-2.5 py-1.5 text-xs text-text transition-colors hover:border-border-2 focus:border-accent focus:outline-none"
      >
        <span className="truncate">{value}</span>
        <span className="text-[10px] text-faint">▼</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className={`absolute left-0 z-50 max-h-56 w-56 overflow-y-auto rounded-md border border-border bg-surface p-1 shadow-elevated ${
              openUpward ? "bottom-full mb-1" : "top-full mt-1"
            }`}
          >
            <input
              type="text"
              placeholder="Search tag..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="mb-1 w-full rounded border border-border bg-bg px-2 py-1 text-xs text-text focus:border-accent focus:outline-none"
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
                      ? "bg-accent-soft font-semibold text-accent-dim"
                      : "text-text hover:bg-surface-2"
                  }`}
                >
                  <span>{tag}</span>
                  {tag === value && <span className="text-accent-dim">✓</span>}
                </button>
              ))}
              {filteredTags.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-muted">No matching tags</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function ReviewDraft() {
  const [startDate, setStartDate] = useState(getTodayLocalDate);
  const [endDate, setEndDate] = useState(getTodayLocalDate);

  const [draft, setDraft] = useState<WorkLogDraft | null>(null);
  const [verification, setVerification] = useState<ReconciliationResult["verification"] | null>(null);
  const [approveSuccess, setApproveSuccess] = useState(false);
  const [draggedIndex, setDraggedIndex] = useState<{ day: string; index: number } | null>(null);

  const generateMutation = useGenerateDraft();
  const approveMutation = useApproveDraft();

  const handleGenerate = () => {
    setApproveSuccess(false);
    generateMutation.mutate(
      { date_range_start: startDate, date_range_end: endDate },
      {
        onSuccess: (data) => {
          setDraft(data.draft);
          setVerification(data.verification);
        },
      },
    );
  };

  const handleApprove = () => {
    if (!draft) return;
    approveMutation.mutate(draft, {
      onSuccess: () => {
        setApproveSuccess(true);
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
        const currentMins = entry.allocations.reduce((sum, a) => sum + a.minutes, 0);
        if (currentMins === 0 || entry.allocations.length === 0) {
          return { ...entry, allocations: [{ block_id: 1, minutes: newMinutes }] };
        }
        if (entry.allocations.length === 1) {
          return {
            ...entry,
            allocations: [{ ...entry.allocations[0], minutes: newMinutes }],
          };
        }
        const ratio = newMinutes / currentMins;
        let allocatedSum = 0;
        const updatedAllocations = entry.allocations.map((a, aIdx) => {
          if (aIdx === entry.allocations.length - 1) {
            const remaining = Math.max(1, newMinutes - allocatedSum);
            return { ...a, minutes: remaining };
          }
          const mins = Math.max(1, Math.round(a.minutes * ratio));
          allocatedSum += mins;
          return { ...a, minutes: mins };
        });
        return { ...entry, allocations: updatedAllocations };
      }),
    });
  };

  const deleteEntry = (entryIndex: number) => {
    if (!draft) return;
    setDraft({
      ...draft,
      entries: draft.entries.filter((_, idx) => idx !== entryIndex),
    });
  };

  const reorderEntriesWithinDay = (day: string, fromIndex: number, toIndex: number) => {
    if (!draft || fromIndex === toIndex) return;
    const dayEntries = draft.entries.filter((e) => e.date === day);
    if (fromIndex < 0 || fromIndex >= dayEntries.length || toIndex < 0 || toIndex >= dayEntries.length) return;

    const reorderedDayEntries = [...dayEntries];
    const [moved] = reorderedDayEntries.splice(fromIndex, 1);
    reorderedDayEntries.splice(toIndex, 0, moved);

    let dayPointer = 0;
    const newEntries = draft.entries.map((entry) => {
      if (entry.date === day) {
        return reorderedDayEntries[dayPointer++];
      }
      return entry;
    });

    setDraft({ ...draft, entries: newEntries });
  };

  const addBlankEntry = (day: string) => {
    if (!draft) return;
    const newEntry: DraftEntry = {
      date: day,
      project: "unidentified",
      allocations: [{ block_id: 1, minutes: 30 }],
      tag: "Coding",
      description: "",
      source_remote_event_ids: [],
    };
    setDraft({
      ...draft,
      entries: [...draft.entries, newEntry],
    });
  };

  const createEntryFromReminder = (reminder: DraftReminder) => {
    if (!draft) return;
    const newEntry: DraftEntry = {
      date: reminder.day,
      project: "unidentified",
      allocations: [{ block_id: 1, minutes: 30 }],
      tag: "Other",
      description: reminder.note,
      source_remote_event_ids: reminder.source_remote_event_ids,
    };
    setDraft({
      ...draft,
      entries: [...draft.entries, newEntry],
    });
  };

  const days = Array.from(
    new Set([
      ...(draft?.entries.map((e) => e.date) ?? []),
      ...(draft?.reminders.map((r) => r.day) ?? []),
      ...(draft ? [startDate] : []),
    ]),
  ).sort();

  return (
    <div className="space-y-8">
      {/* Top Header & Generator Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-surface p-6 shadow-sm">
        <div>
          <h1 className="font-mono text-2xl font-bold text-text">AI Reconciliation</h1>
          <p className="mt-1 text-sm text-muted">
            Review and reconcile your AI-generated work log draft before saving.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 font-mono text-sm">
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-text focus:border-accent focus:outline-none"
            />
            <span className="text-muted">to</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-text focus:border-accent focus:outline-none"
            />
          </div>

          <Button
            variant="primary"
            onClick={handleGenerate}
            disabled={generateMutation.isPending}
            icon={generateMutation.isPending ? <Loading size="sm" /> : undefined}
          >
            {generateMutation.isPending ? "Generating..." : "Generate Draft"}
          </Button>
        </div>
      </div>

      {generateMutation.isError && (
        <div className="rounded-lg border border-danger/30 bg-danger-soft p-4 text-sm text-danger">
          Failed to generate draft: {generateMutation.error.message}
        </div>
      )}

      {approveMutation.isError && (
        <div className="rounded-lg border border-danger/30 bg-danger-soft p-4 text-sm text-danger">
          Failed to approve draft: {approveMutation.error.message}
        </div>
      )}

      {approveSuccess && (
        <div className="rounded-lg border border-accent/30 bg-accent-soft p-4 text-sm font-semibold text-accent-dim">
          ✓ Draft entries successfully approved and saved to database!
        </div>
      )}

      {generateMutation.isPending && (
        <div className="rounded-xl border border-accent/20 bg-surface p-12 text-center shadow-sm space-y-4">
          <div className="flex justify-center">
            <Loading size="lg" />
          </div>
          <h3 className="font-mono text-lg font-bold text-text">Analyzing Activity & Remote Evidence...</h3>
          <p className="text-sm text-muted max-w-md mx-auto">
            Logline is aggregating your local tracker activity logs, fetching remote signals from connected integrations (GitHub, Slack, Jira, Calendar), matching evidence, and synthesizing AI-reconciled Workstream entries.
          </p>
        </div>
      )}

      {!draft && !generateMutation.isPending && (
        <div className="rounded-xl border border-dashed border-border bg-surface/50 p-12 text-center">
          <p className="text-muted">No draft loaded. Select a date range and click "Generate Draft" to start.</p>
        </div>
      )}

      {/* Render Draft Content Per Day */}
      {draft && (
        <div className="space-y-8">
          {days.map((day) => {
            const dayEntries = draft.entries
              .map((e, globalIdx) => ({ entry: e, globalIdx }))
              .filter((item) => item.entry.date === day);
            const dayReminders = draft.reminders.filter((r) => r.day === day);
            const totalDayMinutes = dayEntries.reduce(
              (sum, item) => sum + item.entry.allocations.reduce((aSum, a) => aSum + a.minutes, 0),
              0,
            );
            const residualMinutes = draft.residual_unassigned_minutes.reduce((sum, a) => sum + a.minutes, 0);

            return (
              <div key={day} className="rounded-xl border border-border bg-surface p-6 shadow-sm space-y-6">
                {/* Day Header with Running Total */}
                <div className="flex items-center justify-between border-b border-border pb-4">
                  <h2 className="font-mono text-lg font-bold text-text">{day}</h2>
                  <div className="flex items-center gap-2">
                    <span className="text-xs uppercase tracking-wider text-muted font-medium">Running Total:</span>
                    <span className="rounded-md bg-accent-soft px-2.5 py-1 font-mono text-sm font-bold text-accent-dim">
                      {formatMinutes(totalDayMinutes)}
                    </span>
                  </div>
                </div>

                {/* 2. VERIFICATION ISSUES */}
                {verification && verification.issues.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Verification Issues</h3>
                    {verification.issues.map((issue, idx) => {
                      const isError = issue.severity === "error";
                      return (
                        <div
                          key={idx}
                          className={`flex items-start gap-3 rounded-lg border p-3.5 text-xs ${
                            isError
                              ? "border-danger/40 bg-danger-soft text-danger"
                              : "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                          }`}
                        >
                          <span className="mt-0.5 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase font-bold tracking-wide">
                            {issue.severity}
                          </span>
                          <div className="flex-1">
                            <span className="font-semibold">{issue.check}: </span>
                            <span>{issue.detail}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* 1. ENTRIES TABLE */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Entries</h3>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => addBlankEntry(day)}
                    >
                      + Add entry
                    </Button>
                  </div>
                  {dayEntries.length === 0 ? (
                    <p className="py-4 text-xs italic text-faint">No entries logged for this day.</p>
                  ) : (
                    <div className="relative rounded-lg border border-border">
                      <table className="w-full text-left text-sm">
                        <thead className="bg-surface-2 text-xs font-semibold uppercase text-muted">
                          <tr>
                            <th className="w-10 px-3 py-2"></th>
                            <th className="w-28 px-3 py-2">Time</th>
                            <th className="w-48 px-3 py-2">Tag</th>
                            <th className="px-3 py-2">Description</th>
                            <th className="w-12 px-3 py-2 text-right"></th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {dayEntries.map(({ entry, globalIdx }, localIdx) => {
                            const entryMins = entry.allocations.reduce((sum, a) => sum + a.minutes, 0);

                            return (
                              <tr
                                key={globalIdx}
                                draggable
                                onDragStart={() => setDraggedIndex({ day, index: localIdx })}
                                onDragOver={(e) => e.preventDefault()}
                                onDrop={() => {
                                  if (draggedIndex && draggedIndex.day === day) {
                                    reorderEntriesWithinDay(day, draggedIndex.index, localIdx);
                                    setDraggedIndex(null);
                                  }
                                }}
                                className="group transition-colors hover:bg-surface-2/50"
                              >
                                {/* Drag Handle */}
                                <td className="cursor-grab px-3 py-3 text-faint hover:text-text">
                                  <span className="font-mono text-xs">⋮⋮</span>
                                </td>

                                {/* Editable Hours (HH:MM / minutes) */}
                                <td className="px-3 py-3 font-mono text-xs align-top">
                                  <input
                                    type="text"
                                    value={minutesToHHMM(entryMins)}
                                    onChange={(e) => updateEntryMinutes(globalIdx, parseTimeToMinutes(e.target.value))}
                                    aria-label="Entry hours"
                                    className="w-20 rounded border border-border bg-bg px-2 py-1 text-xs text-text focus:border-accent focus:outline-none"
                                  />
                                </td>

                                {/* Custom Scrollable & Filterable Tag Selector */}
                                <td className="px-3 py-3 align-top">
                                  <TagSelect
                                    value={entry.tag}
                                    onChange={(nextTag) => updateEntry(globalIdx, { tag: nextTag })}
                                  />
                                </td>

                                {/* Multi-line Description Field + Review Reason indicator */}
                                <td className="px-3 py-3 align-top">
                                  <div className="flex items-start gap-2">
                                    <textarea
                                      rows={2}
                                      value={entry.description}
                                      onChange={(e) => updateEntry(globalIdx, { description: e.target.value })}
                                      aria-label="Entry description"
                                      className="w-full rounded border border-border bg-bg px-2.5 py-1.5 text-xs text-text focus:border-accent focus:outline-none min-h-[42px] resize-y"
                                    />
                                    {entry.review_reason && (
                                      <Tooltip content={`AI Uncertainty: ${entry.review_reason}`} side="top">
                                        <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500/20 font-bold text-amber-500 text-[10px] cursor-help">
                                          ⚠
                                        </span>
                                      </Tooltip>
                                    )}
                                  </div>
                                </td>

                                {/* Delete Button */}
                                <td className="px-3 py-3 text-right align-top">
                                  <button
                                    type="button"
                                    onClick={() => deleteEntry(globalIdx)}
                                    aria-label="Delete entry"
                                    className="rounded p-1 text-faint transition-colors hover:bg-danger-soft hover:text-danger"
                                  >
                                    ✕
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {/* 3. REMINDERS (Visually distinct section) */}
                {dayReminders.length > 0 && (
                  <div className="space-y-3 rounded-lg border border-accent/20 bg-accent-soft/30 p-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-accent-dim">
                      Reminders (Unlogged Activity)
                    </h3>
                    <div className="space-y-2">
                      {dayReminders.map((reminder, idx) => (
                        <div
                          key={idx}
                          className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-surface p-3 text-xs border border-border"
                        >
                          <div className="flex items-center gap-2">
                            <span className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] uppercase font-bold text-muted">
                              {reminder.source}
                            </span>
                            <span className="text-text">{reminder.note}</span>
                          </div>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => createEntryFromReminder(reminder)}
                          >
                            + Log time for this
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 4. RESIDUAL / UNASSIGNED TIME */}
                {residualMinutes > 0 && (
                  <div className="rounded-md border border-border/80 bg-surface-2/40 px-3.5 py-2.5 text-xs text-muted">
                    ℹ <span className="font-medium text-text">{residualMinutes} minutes</span> of measured activity wasn't confidently assigned to any entry.
                  </div>
                )}
              </div>
            );
          })}

          {/* Bottom Approve Action Bar */}
          <div className="flex items-center justify-end border-t border-border pt-6">
            <Button
              variant="primary"
              size="lg"
              onClick={handleApprove}
              disabled={approveMutation.isPending || approveSuccess || !draft.entries.length}
              icon={approveMutation.isPending ? <Loading size="sm" /> : undefined}
            >
              {approveSuccess ? "Approved ✓" : approveMutation.isPending ? "Approving..." : "Approve Draft"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
