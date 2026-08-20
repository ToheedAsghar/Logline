import type { IntegrationId } from "@/constants";

export type EntryFormat = "project_log" | "standup";
export type EntryStatus = "draft" | "pending" | "approved" | "discarded";

export interface StandupContent {
  yesterday: string;
  today: string;
  blockers: string;
}

export interface ProjectLogContent {
  text: string;
  origin?: "evidence" | "manual";
  manual_minutes?: number;
}

export type EntryContent = StandupContent | ProjectLogContent;

export interface Entry {
  id: number;
  user_id: number;
  format: EntryFormat;
  content: EntryContent;
  work_date: string;
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

export interface UserResponse {
  id: number;
  email: string;
  name: string | null;
  default_channel: string | null;
  timezone: string | null;
  created_at: string;
}

export const ALL_ENTRY_TAGS = [
  "Coding",
  "Debugging",
  "Code Review",
  "Meeting",
  "Testing",
  "Documentation",
  "Coordination",
  "Deployment",
  "Project Planning",
  "Architecture Design",
  "Designing",
  "Technical Project Setup",
  "Backlog grooming",
  "Support Tickets",
  "Support",
  "R&D",
  "Tech Assessment",
  "Reviews",
  "Reporting/Analysis",
  "Training/Learning",
  "Team Engagement",
  "Team Management",
  "Project Estimations",
  "Presenting",
  "Interviewing",
  "Recruiting",
  "Course Authoring",
  "Account Management",
  "Customer Implementation",
  "Operations",
  "Audit/Compliance",
  "Sales/Client Demo",
  "Marketing Campaigns",
  "Capex",
  "Opex",
  "Other",
] as const;

export type EntryTag = (typeof ALL_ENTRY_TAGS)[number];

export interface BlockAllocation {
  block_id: number;
  minutes: number;
  date?: string;
}

interface DraftEntryBase {
  entry_id?: number;
  date: string;
  project: string | null;
  tag: EntryTag;
  description: string;
  source_remote_event_ids?: string[];
  review_reason?: string | null;
}

export interface EvidenceDraftEntry extends DraftEntryBase {
  entry_id: number;
  origin: "evidence";
  allocations: BlockAllocation[];
  manual_minutes?: never;
}

export interface ManualDraftEntry extends DraftEntryBase {
  origin: "manual";
  allocations: BlockAllocation[];
  manual_minutes?: number;
}

export type DraftEntry = EvidenceDraftEntry | ManualDraftEntry;

export interface DraftReminder {
  note: string;
  source: "github" | "jira" | "slack" | "calendar";
  day: string;
  source_remote_event_ids?: string[];
}

export interface WorkLogDraft {
  entries: DraftEntry[];
  reminders: DraftReminder[];
  residual_unassigned_minutes: BlockAllocation[];
  tracked_wall_clock_minutes: number;
}

export interface VerificationIssue {
  severity: "error" | "warning";
  check: string;
  detail: string;
  block_id?: number | null;
  entry_index?: number | null;
}

export interface VerificationResult {
  passed: boolean;
  issues: VerificationIssue[];
}

export interface ReconciliationResult {
  draft_id: number;
  state: "active" | "approved";
  date_range_start: string;
  date_range_end: string;
  generated_at: string;
  draft: WorkLogDraft;
  verification: VerificationResult;
}

export interface ReconciliationGenerateParams {
  date_range_start: string;
  date_range_end: string;
  replace_draft_id?: number;
}

export interface ReconciliationApproveParams extends ReconciliationGenerateParams {
  draft_id: number;
  draft: WorkLogDraft;
}

export interface DiscardDraftResult {
  draft_id: number;
  state: "discarded";
}

export interface TrackerSyncStatus {
  /** Newest checkpoint across the user's active devices; null when nothing has ever synced. */
  last_synced_at: string | null;
  device_count: number;
}

export interface DeviceEnrollIn {
  name?: string;
}

export interface DeviceEnrollOut {
  device_id: string;
  name: string;
  token: string;
  created_at: string;
}

export type RemoteEventSource = "github" | "jira" | "slack" | "calendar";

export interface RemoteEvent {
  id: number;
  source: RemoteEventSource;
  event_type: string;
  occurred_at: string;
  summary: string | null;
  description: string | null;
  remote_project_id: string | null;
  match_keys: Record<string, unknown> | null;
}

export interface RemoteEventList {
  events: RemoteEvent[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface RemoteEventListParams {
  source?: RemoteEventSource;
  date_range_start?: string;
  date_range_end?: string;
  cursor?: string | null;
  limit?: number;
}
