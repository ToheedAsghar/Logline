import { Loading } from "@/atoms";
import { useEntries } from "@/repositories/hooks";
import type { Entry, ProjectLogContent, StandupContent } from "@/repositories/types";

const FORMAT_LABEL: Record<Entry["format"], string> = {
  standup: "Standup",
  project_log: "Project Log",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function EntryCard({ entry }: { entry: Entry }) {
  return (
    <article className="flex flex-col gap-2 rounded-md border border-border-2 bg-surface px-4 py-3.5">
      <div className="flex items-center gap-2">
        <span className="rounded-sm bg-accent-soft px-2 py-0.5 font-mono text-[11px] text-accent-dim">{FORMAT_LABEL[entry.format]}</span>
        <span className="font-mono text-[11px] text-faint">
          Approved {entry.approved_at ? formatDate(entry.approved_at) : formatDate(entry.created_at)}
        </span>
      </div>
      {entry.format === "standup" ? (
        <dl className="flex flex-col gap-1.5 font-sans text-sm text-text">
          <StandupRow label="Yesterday" value={(entry.content as StandupContent).yesterday} />
          <StandupRow label="Today" value={(entry.content as StandupContent).today} />
          {(entry.content as StandupContent).blockers && <StandupRow label="Blockers" value={(entry.content as StandupContent).blockers} />}
        </dl>
      ) : (
        <p className="whitespace-pre-wrap font-sans text-sm text-text">{(entry.content as ProjectLogContent).text}</p>
      )}
    </article>
  );
}

function StandupRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-16 flex-none font-mono text-[11px] uppercase tracking-wider text-faint">{label}</dt>
      <dd className="text-muted">{value}</dd>
    </div>
  );
}

export default function History() {
  const entries = useEntries({ status: "approved" });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">History</h1>
        <p className="text-sm text-muted">Standups and project logs you&apos;ve approved.</p>
      </div>

      {entries.isLoading && <Loading label="Loading history…" />}
      {entries.isError && <p className="font-mono text-[11px] text-danger">Couldn&apos;t load history — try again.</p>}

      {!entries.isLoading && !entries.isError && entries.data?.length === 0 && (
        <div className="flex flex-col items-start gap-1 rounded-md border border-border bg-surface px-4 py-8">
          <p className="font-sans text-sm font-medium text-text">Nothing here yet.</p>
          <p className="font-sans text-sm text-muted">
            Approve a draft in Compose and it&apos;ll land here — a running record of what you shipped.
          </p>
        </div>
      )}

      {!entries.isLoading && !entries.isError && entries.data && entries.data.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {entries.data.map((entry) => (
            <EntryCard key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
