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

