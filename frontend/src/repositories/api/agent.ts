import type { AgentRunResult, DateRange } from "../types";
import { apiRequest } from "./client";

export function runAgent(task: string, dateRange?: DateRange): Promise<AgentRunResult> {
  return apiRequest<AgentRunResult>("/agent/run", {
    method: "POST",
    body: dateRange ? { task, date_range: dateRange } : { task },
  });
}
