// Confidence formatting helpers. Pure -- no React, no DOM. Used by
// components/ConfBadge.tsx and any place that needs to describe a model
// confidence score in a user-facing string. confTier / confColor are
// already exported from lib/categories.ts; this file fleshes out the
// additional helpers the badge needs.

export type ConfTier = "high" | "mid" | "low";

// Re-export so consumers can import everything from one module.
export function confTier(score: number): ConfTier {
  if (score >= 0.8) return "high";
  if (score >= 0.55) return "mid";
  return "low";
}

// Tier label used in screen-reader announcements and the badge tooltip.
// Plain English so AT users get useful context: not just "92%" but
// "92 percent. High confidence."
export const TIER_LABEL: Record<ConfTier, string> = {
  high: "High confidence",
  mid: "Medium confidence",
  low: "Low confidence",
};

// Build the full aria-label for a confidence badge. Reads naturally:
//   "92.0 percent. High confidence."
export function confAriaLabel(score: number, digits = 1): string {
  const clamped = Math.max(0, Math.min(1, score));
  const num = (clamped * 100).toFixed(digits);
  return `${num} percent. ${TIER_LABEL[confTier(clamped)]}.`;
}

// Format the visible badge text. Defaults to no decimals (so a packed
// table row reads cleanly), but accepts a digits arg so the detail view
// can show "92.0%". We never render >100% even if a caller hands us a
// score above 1 (defensive).
export function confDisplay(score: number, digits = 0): string {
  const clamped = Math.max(0, Math.min(1, score));
  return `${(clamped * 100).toFixed(digits)}%`;
}

// Pick a CSS color variable name (NOT including `var()`) for the tier.
// Components compose this into `var(--color-conf-high)` themselves. The
// indirection lets future themes swap palettes without touching every
// call site.
export function confTokenName(score: number): string {
  const t = confTier(score);
  if (t === "high") return "--color-conf-high";
  if (t === "mid") return "--color-conf-mid";
  return "--color-conf-low";
}

// Used by the badge's tooltip / title attribute -- one-line numeric +
// tier hint that's a touch more compact than the aria-label.
export function confTooltip(score: number): string {
  const clamped = Math.max(0, Math.min(1, score));
  return `${(clamped * 100).toFixed(2)}% · ${TIER_LABEL[confTier(clamped)].toLowerCase()}`;
}
