/**
 * Design tokens extracted from the Claude Design handoff
 * (logline-frontend-build/project/Logline.dc.html).
 *
 * Source of truth in the handoff: the `DARK` / `LIGHT` palette objects and the
 * `confStyle`/`dot`/`confPillStyle` builders inside the component's
 * `renderVals()`. The handoff has no separate "tokens" file — these values
 * are read directly off that component's JS.
 *
 * These are exported as plain data so both Tailwind (via `index.css`'s
 * `@theme`) and components that need raw values (e.g. inline SVG, canvas)
 * can consume the same numbers.
 */

export type ThemeName = "dark" | "light";
export type AccentName = "lime" | "amber" | "mint";

/** Hue angles the handoff swaps in for the accent color, dark theme only —
 * see `renderVals()`: `const hue = ({ lime:122, amber:85, mint:160 })[this.props.accent]`.
 * The light theme's accent is hard-coded in the handoff and does not shift
 * with this setting. */
export const ACCENT_HUES: Record<AccentName, number> = {
  lime: 122,
  amber: 85,
  mint: 160,
};

export interface ColorPalette {
  bg: string;
  surface: string;
  surface2: string;
  border: string;
  border2: string;
  text: string;
  muted: string;
  faint: string;
  accent: string;
  accentInk: string;
  accentDim: string;
  accentSoft: string;
  danger: string;
  dangerSoft: string;
  shadow: string;
  sidebarBg: string;
  sidebarSurface: string;
  sidebarText: string;
  sidebarMuted: string;
  sidebarBorder: string;
}

export const PALETTES: Record<ThemeName, ColorPalette> = {
  dark: {
    bg: "oklch(0.165 0.008 260)",
    surface: "oklch(0.205 0.009 260)",
    surface2: "oklch(0.25 0.011 260)",
    border: "oklch(0.30 0.012 260)",
    border2: "oklch(0.40 0.014 260)",
    text: "oklch(0.94 0.006 260)",
    muted: "oklch(0.70 0.012 260)",
    faint: "oklch(0.55 0.012 260)",
    accent: "oklch(0.87 0.19 122)",
    accentInk: "oklch(0.24 0.05 122)",
    accentDim: "oklch(0.80 0.15 122)",
    accentSoft: "oklch(0.87 0.19 122 / 0.16)",
    danger: "oklch(0.70 0.17 25)",
    dangerSoft: "oklch(0.70 0.17 25 / 0.16)",
    shadow: "0 16px 48px oklch(0 0 0 / 0.55)",
    sidebarBg: "oklch(0.165 0.008 260)",
    sidebarSurface: "oklch(0.25 0.011 260)",
    sidebarText: "oklch(0.94 0.006 260)",
    sidebarMuted: "oklch(0.70 0.012 260)",
    sidebarBorder: "oklch(0.30 0.012 260)",
  },
  // `light` is the actual default theme: the handoff's component state
  // initializes `theme: 'light'` and its `defaultTheme` prop defaults to
  // 'light' too (confirmed against the bundled Logline.html export).
  // Note: the handoff's LIGHT palette hard-codes `accent` to this green
  // regardless of the `accent` prop — only the dark theme re-hues it.
  light: {
    bg: "oklch(0.966 0.011 95)",
    surface: "oklch(0.992 0.007 100)",
    surface2: "oklch(0.94 0.014 96)",
    border: "oklch(0.875 0.016 100)",
    border2: "oklch(0.78 0.022 108)",
    text: "oklch(0.235 0.026 150)",
    muted: "oklch(0.44 0.028 152)",
    faint: "oklch(0.58 0.026 148)",
    accent: "oklch(0.49 0.108 156)",
    accentInk: "oklch(0.97 0.02 105)",
    accentDim: "oklch(0.49 0.108 156)",
    accentSoft: "oklch(0.49 0.108 156 / 0.13)",
    danger: "oklch(0.52 0.16 40)",
    dangerSoft: "oklch(0.52 0.16 40 / 0.12)",
    shadow: "0 18px 50px oklch(0.30 0.05 155 / 0.16)",
    sidebarBg: "oklch(0.215 0.022 158)",
    sidebarSurface: "oklch(0.29 0.026 158)",
    sidebarText: "oklch(0.945 0.012 120)",
    sidebarMuted: "oklch(0.68 0.02 150)",
    sidebarBorder: "oklch(0.325 0.024 158)",
  },
};

/** Given a theme + accent choice, returns the palette with the accent hue
 * swapped in exactly the way the handoff's `renderVals()` does it. */
export function resolvePalette(theme: ThemeName, accent: AccentName): ColorPalette {
  const base = PALETTES[theme];
  if (theme !== "dark") return base;
  const hue = ACCENT_HUES[accent];
  return {
    ...base,
    accent: `oklch(0.87 0.19 ${hue})`,
    accentInk: `oklch(0.24 0.05 ${hue})`,
    accentDim: `oklch(0.80 0.15 ${hue})`,
    accentSoft: `oklch(0.87 0.19 ${hue} / 0.16)`,
  };
}

/**
 * Typography: the handoff's two-role type system.
 *  - `sans` (Space Grotesk) carries generated / written / human content:
 *    headings, body copy, draft text, buttons.
 *  - `mono` (IBM Plex Mono) carries proven / factual / system data:
 *    timestamps, eyebrows, source chips, evidence values, keycaps.
 */
export const FONT_FAMILIES = {
  sans: "'Space Grotesk', system-ui, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, monospace",
} as const;

/** Radii actually reused across the handoff's controls (buttons, inputs,
 * cards, pills). One-off values outside this set (e.g. the 27px FAB) are
 * left as arbitrary Tailwind values at the call site rather than forced
 * into the scale. */
export const RADII = {
  xs: "4px",
  sm: "7px",
  md: "9px",
  lg: "12px",
  xl: "14px",
  "2xl": "16px",
  "3xl": "18px",
  pill: "999px",
} as const;

/** Confidence tiers: the core visual vocabulary of the product. Every piece
 * of data on the timeline is rendered through one of these treatments so a
 * user can tell at a glance how much to trust it — see the auth-screen
 * legend ("Proven — solid, evidence-backed", "Estimated — inferred,
 * editable", "Gap — an open question") and `confStyle()`/`dot()` in the
 * handoff.
 */
export type ConfidenceTier = "proven" | "estimated" | "gap" | "personal";

export interface ConfidenceTierConfig {
  label: string;
  description: string;
  /** CSS border-style for the block/swatch outline. */
  borderStyle: "solid" | "dashed" | "dotted";
  /** Whether a 3px accent-colored left border marks it (proven/estimated only). */
  hasLeftAccent: boolean;
  /** Block opacity when rendered on the timeline. */
  opacity: number;
  /** Dot indicator style used in timeline chips / legends. */
  dot: "solid-accent" | "dashed-accent" | "solid-faint";
}

export const CONFIDENCE_TIERS: Record<ConfidenceTier, ConfidenceTierConfig> = {
  proven: {
    label: "Proven",
    description: "solid, evidence-backed",
    borderStyle: "solid",
    hasLeftAccent: true,
    opacity: 1,
    dot: "solid-accent",
  },
  estimated: {
    label: "Estimated",
    description: "inferred, editable",
    borderStyle: "dashed",
    hasLeftAccent: true,
    opacity: 0.82,
    dot: "dashed-accent",
  },
  gap: {
    label: "Gap",
    description: "an open question",
    borderStyle: "dotted",
    hasLeftAccent: false,
    opacity: 1,
    dot: "solid-faint",
  },
  personal: {
    label: "Away",
    description: "time away, not counted as work",
    borderStyle: "solid",
    hasLeftAccent: false,
    opacity: 0.9,
    dot: "solid-faint",
  },
};

/** Keyframe names ported verbatim from the handoff's <style> block (see
 * index.css for the @keyframes bodies). Referenced by name so components
 * don't hardcode animation strings. */
export const KEYFRAMES = {
  blink: "ll-blink",
  type: "ll-type",
  sweep: "ll-sweep",
  pop: "ll-pop",
  slide: "ll-slide",
  rise: "ll-rise",
  toast: "ll-toast",
  toastbar: "ll-toastbar",
  pulse: "ll-pulse",
  dots: "ll-dots",
  agentin: "ll-agentin",
} as const;
