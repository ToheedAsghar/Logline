import { useEffect, useState } from "react";
import { Button, Checkbox, ConfidenceTier, Input, Loading, Textarea, Tooltip } from "@/atoms";
import {
  ApprovalTransition,
  EditableTimeField,
  GapPrompt,
  IntegrationCard,
  TimelineBlock,
} from "@/molecules";
import { CONFIDENCE_TIERS, type ConfidenceTier as Tier, type ThemeName } from "@/constants/tokens";
import type { Entry, Event, Integration } from "@/repositories/types";

const TIERS: Tier[] = ["proven", "estimated", "gap", "personal"];

const MOCK_EVENTS: Event[] = [
  {
    id: 1,
    source: "github",
    type: "pull_request_merged",
    timestamp: "2026-07-08T14:00:00.000Z",
    event_metadata: {
      title: "Merge PR #482: Add molecules layer",
      summary: "Composed TimelineBlock, GapPrompt, and four more molecules from Phase 1's atoms.",
      end_timestamp: "2026-07-08T15:30:00.000Z",
    },
    confidence: "proven",
    created_at: "2026-07-08T15:30:05.000Z",
  },
  {
    id: 2,
    source: "calendar",
    type: "focus_block",
    timestamp: "2026-07-08T09:00:00.000Z",
    event_metadata: { end_timestamp: "2026-07-08T10:30:00.000Z" },
    confidence: "estimated",
    created_at: "2026-07-08T10:30:05.000Z",
  },
  {
    id: 3,
    source: "personal",
    type: "lunch",
    timestamp: "2026-07-08T12:00:00.000Z",
    event_metadata: { title: "Lunch", end_timestamp: "2026-07-08T13:00:00.000Z" },
    confidence: "proven",
    created_at: "2026-07-08T13:00:05.000Z",
  },
];

const MOCK_INTEGRATIONS: Integration[] = [
  { id: 1, source: "github", status: "connected", last_synced_at: "2026-07-08T14:31:00.000Z", created_at: "2026-01-01T00:00:00.000Z" },
  { id: 2, source: "slack", status: "error", last_synced_at: "2026-07-07T09:00:00.000Z", created_at: "2026-01-01T00:00:00.000Z" },
  { id: 3, source: "jira", status: "disconnected", last_synced_at: null, created_at: "2026-01-01T00:00:00.000Z" },
];

const MOCK_DRAFT_ENTRY: Entry = {
  id: 101,
  user_id: 1,
  format: "standup",
  content: { yesterday: "Shipped Phase 2 hooks.", today: "Building Phase 3 molecules.", blockers: "" },
  status: "draft",
  created_at: "2026-07-08T09:00:00.000Z",
  approved_at: null,
};

const MOCK_APPROVED_ENTRY: Entry = {
  id: 102,
  user_id: 1,
  format: "project_log",
  content: { text: "Shipped the molecules layer." },
  status: "approved",
  created_at: "2026-07-07T09:00:00.000Z",
  approved_at: "2026-07-07T16:00:00.000Z",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 border-b border-border pb-10">
      <h2 className="font-mono text-[11px] uppercase tracking-wider text-faint">{title}</h2>
      {children}
    </section>
  );
}

function Swatch({ name, value }: { name: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-9 w-9 flex-none rounded-md border border-border" style={{ background: value }} />
      <div className="min-w-0">
        <div className="text-sm font-medium">{name}</div>
        <div className="truncate font-mono text-[11px] text-faint">{value}</div>
      </div>
    </div>
  );
}

const CheckIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 13l4 4 10-11" />
  </svg>
);

const RefreshIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 12h3.5l1.6-5 3.2 11 1.9-6H17" />
    <path d="M17 8h4M19 6v4" opacity={0.55} />
  </svg>
);

/**
 * Reference/QA page for the Phase 1–3 design-system layers (tokens, atoms,
 * molecules) in isolation, outside any real data flow. Kept reachable at
 * `/styleguide` (unauthenticated, not linked from the app nav) rather than
 * deleted — useful for visually spot-checking a component change without
 * needing a logged-in session or live backend.
 */
export default function StyleGuide() {
  const [theme, setTheme] = useState<ThemeName>("light");
  const [working, setWorking] = useState(false);
  const [checked, setChecked] = useState(true);
  const [timeRange, setTimeRange] = useState<{ start: string; end?: string | null }>({
    start: "2026-07-08T09:00:00.000Z",
    end: "2026-07-08T10:30:00.000Z",
  });
  const [unrelatedFlag, setUnrelatedFlag] = useState(true);

  // index.css's palette variables are scoped to `:root[data-theme=...]` (the
  // `<html>` element), not an arbitrary descendant — the toggle has to set the
  // attribute there, not just on this component's wrapper div.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return (
    <div className="min-h-screen bg-bg font-sans text-text transition-colors">
      <div className="mx-auto flex max-w-4xl flex-col gap-12 px-8 py-12">
        <header className="flex items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center gap-px rounded-md bg-accent">
                <span className="font-mono text-base font-bold text-accent-ink">l</span>
                <span className="h-4 w-1 rounded-[1px] bg-accent-ink animate-ll-blink" />
              </span>
              <span className="font-mono text-lg font-semibold">logline</span>
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight">Style Guide — Tokens, Atoms &amp; Molecules</h1>
            <p className="mt-1 max-w-prose text-sm text-muted">
              Design system extracted from the Claude Design handoff, wired into Tailwind, and the atom/molecule
              layers built on top of it. Reference only — the real app lives behind /login.
            </p>
          </div>
          <div className="flex gap-1 rounded-lg border border-border bg-bg p-1">
            <button
              onClick={() => setTheme("light")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${theme === "light" ? "bg-accent text-accent-ink" : "text-muted"}`}
            >
              Light
            </button>
            <button
              onClick={() => setTheme("dark")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${theme === "dark" ? "bg-accent text-accent-ink" : "text-muted"}`}
            >
              Dark
            </button>
          </div>
        </header>

        <Section title="Color tokens">
          <div className="grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-3">
            <Swatch name="bg" value="var(--color-bg)" />
            <Swatch name="surface" value="var(--color-surface)" />
            <Swatch name="surface-2" value="var(--color-surface-2)" />
            <Swatch name="border" value="var(--color-border)" />
            <Swatch name="border-2" value="var(--color-border-2)" />
            <Swatch name="text" value="var(--color-text)" />
            <Swatch name="muted" value="var(--color-muted)" />
            <Swatch name="faint" value="var(--color-faint)" />
            <Swatch name="accent" value="var(--color-accent)" />
            <Swatch name="accent-ink" value="var(--color-accent-ink)" />
            <Swatch name="accent-dim" value="var(--color-accent-dim)" />
            <Swatch name="danger" value="var(--color-danger)" />
          </div>
        </Section>

        <Section title="Typography — two-role system">
          <div className="flex flex-col gap-3">
            <div>
              <div className="font-sans text-lg font-semibold">Space Grotesk — generated &amp; written content</div>
              <p className="mt-1 max-w-prose font-sans text-sm text-muted">
                Draft standups, entry titles, buttons, and body copy read in this humanist sans — anything a person
                (or the agent, writing on their behalf) composed.
              </p>
            </div>
            <div>
              <div className="font-mono text-base font-semibold">IBM Plex Mono — proven &amp; factual data</div>
              <p className="mt-1 max-w-prose font-mono text-[13px] text-muted">
                Timestamps, source chips, eyebrows, and evidence values use this mono to signal "this came from a
                system, not from prose."
              </p>
            </div>
          </div>
        </Section>

        <Section title="Confidence tiers">
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-6">
              {TIERS.map((tier) => (
                <div key={tier} className="flex items-center gap-2.5">
                  <ConfidenceTier tier={tier} shape="swatch" />
                  <div>
                    <div className="text-sm font-medium">{CONFIDENCE_TIERS[tier].label}</div>
                    <div className="text-xs text-muted">{CONFIDENCE_TIERS[tier].description}</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-3">
              {TIERS.map((tier) => (
                <div key={tier} className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2">
                  <ConfidenceTier tier={tier} shape="dot" />
                  <span className="text-xs text-muted">dot</span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-3">
              {TIERS.map((tier) => (
                <ConfidenceTier key={tier} tier={tier} shape="pill" />
              ))}
            </div>
          </div>
        </Section>

        <Section title="Button">
          <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" icon={<CheckIcon />}>
                Primary
              </Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="subtle" icon={<RefreshIcon />}>
                Subtle
              </Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="danger">Danger</Button>
              <Button variant="danger-solid">Danger solid</Button>
              <Button variant="secondary" iconOnly aria-label="Close">
                ✕
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button size="sm">Small</Button>
              <Button size="md">Medium</Button>
              <Button size="lg">Large</Button>
              <Button disabled>Disabled</Button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" working={working} workingLabel="Checking tools…" onClick={() => setWorking((w) => !w)}>
                {working ? "Working" : "Generate standup"}
              </Button>
              <span className="text-xs text-muted">↑ click to toggle the agent-working state (not a spinner)</span>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Loading label="Checking your tools…" />
              <Loading label="Correlating signals…" size="sm" />
            </div>
          </div>
        </Section>

        <Section title="Input">
          <div className="flex max-w-sm flex-col gap-3">
            <Input placeholder="you@company.dev" />
            <Input placeholder="Disabled" disabled />
            <Textarea placeholder="What are you working on?" rows={3} />
          </div>
        </Section>

        <Section title="Checkbox">
          <div className="flex flex-col gap-3">
            <Checkbox label="Voice-note affordances" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            <Checkbox label="Disabled" disabled />
          </div>
        </Section>

        <Section title="Tooltip">
          <div className="flex gap-4">
            <Tooltip content="Check your connected tools for new activity">
              <Button variant="secondary" icon={<RefreshIcon />}>
                Refresh
              </Button>
            </Tooltip>
            <Tooltip content="Quick capture (C)" side="bottom">
              <Button variant="primary" iconOnly aria-label="Quick capture">
                +
              </Button>
            </Tooltip>
          </div>
        </Section>

        <div className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold tracking-tight">Phase 3 — Molecules</h2>
          <p className="max-w-prose text-sm text-muted">Composed from the Phase 1 atoms above, wired to the Phase 2 hooks.</p>
        </div>

        <Section title="TimelineBlock">
          <div className="flex flex-col gap-2.5">
            {MOCK_EVENTS.map((event) => (
              <TimelineBlock key={event.id} event={event} onSelect={(e) => console.log("open entry detail (stub)", e.id)} />
            ))}
          </div>
        </Section>

        <Section title="GapPrompt">
          <GapPrompt start="2026-07-08T10:30:00.000Z" end="2026-07-08T12:00:00.000Z" />
        </Section>

        <Section title="EditableTimeField">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2.5">
              <span className="text-sm text-muted">Focus block</span>
              <EditableTimeField start={timeRange.start} end={timeRange.end} onConfirm={setTimeRange} />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                label="Unrelated flag (should survive editing the time above)"
                checked={unrelatedFlag}
                onChange={(e) => setUnrelatedFlag(e.target.checked)}
              />
            </div>
          </div>
        </Section>

        <Section title="IntegrationCard">
          <div className="flex flex-col gap-2.5">
            {MOCK_INTEGRATIONS.map((integration) => (
              <IntegrationCard key={integration.id} integration={integration} />
            ))}
          </div>
        </Section>

        <Section title="ApprovalTransition">
          <div className="flex flex-wrap items-center gap-4">
            <ApprovalTransition entry={MOCK_DRAFT_ENTRY} />
            <ApprovalTransition entry={MOCK_APPROVED_ENTRY} />
          </div>
        </Section>
      </div>
    </div>
  );
}
