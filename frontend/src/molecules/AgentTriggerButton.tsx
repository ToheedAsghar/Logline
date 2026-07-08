import { Button, type ButtonVariant } from "@/atoms";
import { useRunAgent } from "@/repositories/hooks";
import type { AgentRunResult, DateRange } from "@/repositories/types";

export interface AgentTriggerButtonProps {
  task: string;
  dateRange?: DateRange;
  label: string;
  workingLabel?: string;
  variant?: ButtonVariant;
  onSuccess?: (result: AgentRunResult) => void;
}

/**
 * Binds `Button`'s `working` variant straight to `useRunAgent()` — the button
 * itself already renders the brand cursor motif (not a spinner) while
 * `isPending`, so this component only needs to wire state through, never
 * reimplement the loading visual.
 */
export function AgentTriggerButton({ task, dateRange, label, workingLabel = "Working…", variant = "primary", onSuccess }: AgentTriggerButtonProps) {
  const runAgent = useRunAgent();

  return (
    <div className="flex flex-col items-start gap-1.5">
      <Button
        variant={variant}
        working={runAgent.isPending}
        workingLabel={workingLabel}
        onClick={() => runAgent.mutate({ task, dateRange }, { onSuccess })}
      >
        {label}
      </Button>
      {runAgent.isError && <span className="font-mono text-[11px] text-danger">Agent run failed — try again.</span>}
    </div>
  );
}

/** Primary trigger: gathers evidence *and* synthesizes it into a draft Entry. */
export function GenerateStandupTrigger(props: Omit<AgentTriggerButtonProps, "task" | "label" | "variant" | "workingLabel">) {
  return (
    <AgentTriggerButton
      {...props}
      task="generate today's standup"
      label="Generate Standup"
      workingLabel="Checking your tools…"
      variant="primary"
    />
  );
}

/** Secondary trigger: evidence-gathering only, no draft synthesis. */
export function RefreshTimelineTrigger(props: Omit<AgentTriggerButtonProps, "task" | "label" | "variant" | "workingLabel">) {
  return (
    <AgentTriggerButton
      {...props}
      task="what did I work on today"
      label="Refresh Timeline"
      workingLabel="Refreshing…"
      variant="secondary"
    />
  );
}
