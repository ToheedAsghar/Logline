import { useEffect, useRef, useState } from "react";
import { cn } from "@/common/utils";
import { Button } from "@/atoms";
import { useApproveEntry } from "@/repositories/hooks";
import type { Entry } from "@/repositories/types";

const CheckIcon = ({ className }: { className?: string }) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={3}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
  >
    <path d="M5 13l4 4 10-11" />
  </svg>
);

export interface ApprovalTransitionProps {
  entry: Pick<Entry, "id" | "status">;
  className?: string;
}

/**
 * The one deliberate animation moment in the app (per the design brief —
 * everything else stays calm/static): draft/pending render as a plain,
 * static "Approve" action, but the flip to `approved` plays a one-time
 * pop + rise using the existing `ll-pop`/`ll-agentin` keyframes. Only fires
 * on the actual transition during this session — an entry that *loads*
 * already approved renders the settled state with no animation.
 */
export function ApprovalTransition({ entry, className }: ApprovalTransitionProps) {
  const approveEntry = useApproveEntry();
  const prevStatusRef = useRef(entry.status);
  const [justApproved, setJustApproved] = useState(false);

  useEffect(() => {
    if (prevStatusRef.current !== "approved" && entry.status === "approved") {
      setJustApproved(true);
    }
    prevStatusRef.current = entry.status;
  }, [entry.status]);

  if (entry.status === "approved") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm bg-accent-soft px-2.5 py-1 font-mono text-[11px] text-accent-dim",
          justApproved && "animate-ll-agentin",
          className,
        )}
      >
        <CheckIcon className={cn("h-3 w-3", justApproved && "animate-ll-pop")} />
        Approved
      </span>
    );
  }

  return (
    <div className={cn("flex flex-col items-start gap-1.5", className)}>
      <Button
        variant="primary"
        size="sm"
        icon={<CheckIcon className="h-3.5 w-3.5" />}
        working={approveEntry.isPending}
        workingLabel="Approving…"
        onClick={() => approveEntry.mutate(entry.id)}
      >
        Approve
      </Button>
      {approveEntry.isError && <span className="font-mono text-[11px] text-danger">Couldn&apos;t approve — try again.</span>}
    </div>
  );
}
