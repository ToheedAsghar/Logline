import { useMutation, useQueryClient } from "@tanstack/react-query";
import { runAgent } from "../api/agent";
import type { DateRange } from "../types";
import { TIMELINE_KEY } from "./useTimeline";

interface RunAgentInput {
  task: string;
  dateRange?: DateRange;
}

/**
 * Mutation hook backing "Generate Standup" / "Refresh Timeline". `isPending`
 * reflects the full run (multiple LLM tool-call rounds + real MCP calls, see
 * backend/app/agent/runner.py) — bind Button's `working` prop straight to it.
 */
export function useRunAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ task, dateRange }: RunAgentInput) => runAgent(task, dateRange),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TIMELINE_KEY] });
    },
  });
}
