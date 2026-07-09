/**
 * Domain types mirroring the backend's Pydantic schemas exactly (see
 * `backend/app/schemas/`). Dates/timestamps are ISO 8601 strings, matching
 * what `datetime` fields serialize to over JSON — callers that need a `Date`
 * convert at the point of use.
 */
import type { IntegrationId } from "@/constants/integrations";

export type ConfidenceLevel = "proven" | "estimated" | "gap";

export interface Event {
  id: number;
  source: string;
  type: string;
  timestamp: string;
  event_metadata: Record<string, unknown> | null;
  confidence: ConfidenceLevel;
  created_at: string;
}

export type EntryFormat = "project_log" | "standup";
export type EntryStatus = "draft" | "pending" | "approved";

export interface StandupContent {
  yesterday: string;
  today: string;
  blockers: string;
}

export interface ProjectLogContent {
  text: string;
}

export type EntryContent = StandupContent | ProjectLogContent;

export interface Entry {
  id: number;
  user_id: number;
  format: EntryFormat;
  content: EntryContent;
  status: EntryStatus;
  created_at: string;
  approved_at: string | null;
}

export interface EntryUpdate {
  content?: EntryContent;
  status?: EntryStatus;
  approved_at?: string;
}

export type IntegrationStatus = "connected" | "disconnected" | "error";

export interface Integration {
  id: number;
  source: IntegrationId;
  status: IntegrationStatus;
  last_synced_at: string | null;
  created_at: string;
}

export interface DateRange {
  start: string;
  end: string;
}

export interface AgentRunResult {
  response: string;
  events: Event[];
  /** Id of the draft entry created via write_draft_entry during this run, or
   * null if the run didn't produce one (e.g. evidence-gathering only). */
  created_entry_id: number | null;
}

export interface UserResponse {
  id: number;
  email: string;
  name: string | null;
  default_channel: string | null;
  created_at: string;
}
