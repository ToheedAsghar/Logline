import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/common/utils";
import { Button, Loading, Textarea } from "@/atoms";
import { AgentTriggerButton, ApprovalTransition } from "@/molecules";
import { ENTRIES_KEY, useEntries, useUpdateEntry } from "@/repositories/hooks";
import type { AgentRunResult, Entry, EntryFormat, ProjectLogContent, StandupContent } from "@/repositories/types";

type Format = EntryFormat;

const FORMAT_LABEL: Record<Format, string> = {
  standup: "Standup",
  project_log: "Project Log",
};

/**
 * Local editable draft of an entry's content, seeded from the entry only
 * when its `id` changes — a background refetch (e.g. after Approve) must
 * never clobber text the user is mid-edit on. Same pattern as
 * `EditableTimeField`'s draft state.
 */
function useEditableContent(entry: Entry | undefined) {
  const [standup, setStandup] = useState<StandupContent>({ yesterday: "", today: "", blockers: "" });
  const [projectLog, setProjectLog] = useState<ProjectLogContent>({ text: "" });
  const [seededId, setSeededId] = useState<number | null>(null);

  useEffect(() => {
    if (!entry || entry.id === seededId) return;
    if (entry.format === "standup") {
      setStandup(entry.content as StandupContent);
    } else {
      setProjectLog(entry.content as ProjectLogContent);
    }
    setSeededId(entry.id);
  }, [entry, seededId]);

  return { standup, setStandup, projectLog, setProjectLog };
}

export default function OutputComposer() {
  const [format, setFormat] = useState<Format>("standup");
  // Whether the most recent Generate click reported no draft, so the "no
  // draft" message can be worded as a run outcome rather than plain idle
  // state. Purely cosmetic -- fine to lose on navigation.
  const [justRanWithNoDraft, setJustRanWithNoDraft] = useState(false);
  const queryClient = useQueryClient();

  // Source of truth for "is there a draft to show" is the database, not a
  // run result held in local state -- recovers a completed draft on mount
  // (nav away/back, full reload, whatever) instead of only within the
  // session that triggered the run. Most recent first, so [0] is current.
  const draftsQuery = useEntries({ status: "draft", format });
  const draft = draftsQuery.data?.[0];

  const { standup, setStandup, projectLog, setProjectLog } = useEditableContent(draft);
  const updateEntry = useUpdateEntry();

  const handleSave = () => {
    if (!draft) return;
    updateEntry.mutate({ id: draft.id, patch: { content: draft.format === "standup" ? standup : projectLog } });
  };

  const handleGenerateSuccess = (result: AgentRunResult) => {
    setJustRanWithNoDraft(result.created_entry_id === null);
    queryClient.invalidateQueries({ queryKey: [ENTRIES_KEY] });
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Compose</h1>
          <p className="text-sm text-muted">Generate a draft from today&apos;s evidence, then edit before approving.</p>
        </div>
        <div className="flex gap-1 rounded-lg border border-border bg-surface p-1">
          {(["standup", "project_log"] as const).map((f) => (
            <button
              key={f}
              onClick={() => {
                setFormat(f);
                setJustRanWithNoDraft(false);
              }}
              className={cn("rounded-md px-3 py-1.5 text-xs font-semibold", format === f ? "bg-accent text-accent-ink" : "text-muted")}
            >
              {FORMAT_LABEL[f]}
            </button>
          ))}
        </div>
      </div>

      <AgentTriggerButton
        task={format === "standup" ? "generate today's standup" : "generate today's project log"}
        label={`Generate ${FORMAT_LABEL[format]}`}
        workingLabel="Checking your tools…"
        onSuccess={handleGenerateSuccess}
      />

      {draftsQuery.isLoading && <Loading label="Loading draft…" />}
      {draftsQuery.isError && <p className="font-mono text-[11px] text-danger">Couldn&apos;t load the draft — try again.</p>}

      {!draftsQuery.isLoading && !draftsQuery.isError && !draft && justRanWithNoDraft && (
        <div className="flex flex-col items-start gap-1 rounded-md border border-border bg-surface px-4 py-6">
          <p className="font-sans text-sm font-medium text-text">That run didn&apos;t produce a draft.</p>
          <p className="font-sans text-sm text-muted">Try again — ask it to generate a standup or project log.</p>
        </div>
      )}

      {!draftsQuery.isLoading && !draftsQuery.isError && !draft && !justRanWithNoDraft && (
        <div className="flex flex-col items-start gap-1 rounded-md border border-border bg-surface px-4 py-6">
          <p className="font-sans text-sm font-medium text-text">No draft yet.</p>
          <p className="font-sans text-sm text-muted">Generate one above to get started.</p>
        </div>
      )}

      {draft && (
        <div className="flex flex-col gap-4 rounded-md border border-border-2 bg-surface p-4">
          {draft.format === "standup" ? (
            <>
              <Field label="Yesterday">
                <Textarea rows={3} value={standup.yesterday} onChange={(e) => setStandup((s) => ({ ...s, yesterday: e.target.value }))} />
              </Field>
              <Field label="Today">
                <Textarea rows={3} value={standup.today} onChange={(e) => setStandup((s) => ({ ...s, today: e.target.value }))} />
              </Field>
              <Field label="Blockers">
                <Textarea rows={2} value={standup.blockers} onChange={(e) => setStandup((s) => ({ ...s, blockers: e.target.value }))} />
              </Field>
            </>
          ) : (
            <Field label="Project log">
              <Textarea rows={6} value={projectLog.text} onChange={(e) => setProjectLog({ text: e.target.value })} />
            </Field>
          )}

          {updateEntry.isError && <p className="font-mono text-[11px] text-danger">Couldn&apos;t save — try again.</p>}

          <div className="flex items-center justify-between gap-3">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleSave}
              working={updateEntry.isPending}
              workingLabel="Saving…"
            >
              Save changes
            </Button>
            <ApprovalTransition entry={draft} />
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="font-mono text-[11px] uppercase tracking-wider text-faint">{label}</span>
      {children}
    </label>
  );
}
