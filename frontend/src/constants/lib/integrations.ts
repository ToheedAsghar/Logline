/**
 * The fixed set of integration sources the handoff designs against
 * (`state.integrations` / `GEN_FIND` in Logline.dc.html). Order matches the
 * handoff's integration list and the source-checking sequence shown in the
 * Compose screen's "agent working" state.
 */
export type IntegrationId = "github" | "jira" | "calendar" | "slack" | (string & {});

export interface IntegrationSource {
  id: IntegrationId;
  name: string;
}

export const INTEGRATION_SOURCES: IntegrationSource[] = [
  { id: "github", name: "GitHub" },
  { id: "jira", name: "Jira" },
  { id: "calendar", name: "Google Calendar" },
  { id: "slack", name: "Slack" },
];

export const SOURCE_COLORS: Record<string, { bg: string; color: string }> = {
  github: { bg: "#F5F2EA", color: "#191917" },
  jira: { bg: "#EBF3FB", color: "#0052CC" },
  calendar: { bg: "#EBF3FB", color: "#1A73E8" },
  slack: { bg: "#FBEBF3", color: "#4A154B" },
};
