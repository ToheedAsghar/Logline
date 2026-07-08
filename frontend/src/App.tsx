import { useState } from "react";
import { Button, Checkbox, ConfidenceTier, Input, Loading, Textarea, Tooltip } from "@/atoms";
import { CONFIDENCE_TIERS, type ConfidenceTier as Tier, type ThemeName } from "@/constants/tokens";

const TIERS: Tier[] = ["proven", "estimated", "gap", "personal"];

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

export default function App() {
  const [theme, setTheme] = useState<ThemeName>("light");
  const [working, setWorking] = useState(false);
  const [checked, setChecked] = useState(true);

  return (
    <div data-theme={theme} className="min-h-screen bg-bg font-sans text-text transition-colors">
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
            <h1 className="mt-3 text-2xl font-semibold tracking-tight">Phase 1 — Tokens &amp; Atoms</h1>
            <p className="mt-1 max-w-prose text-sm text-muted">
              Design system extracted from the Claude Design handoff, wired into Tailwind, and the atom layer built on
              top of it.
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
      </div>
    </div>
  );
}
