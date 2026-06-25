// Pure content + window helpers for the /stats KPI explainer popovers (F34).
// The four top stat cards (Lifetime shots / Mean confidence / P95 latency /
// Corrections) each show a single number; a hover/focus popover explains
// what it measures, how it's computed, and which window it covers. Keeping
// the copy + the window-phrasing math here (DOM-free) makes it unit-testable
// and lets the popover component stay a thin renderer -- mirrors the pattern
// established by lib/category-legend.ts for the class-mix chips.

// Stable identifiers for each explainable KPI. The /stats page maps these to
// the matching card.
export type StatId = "lifetime" | "mean_confidence" | "p95_latency" | "corrections";

export type StatExplainer = {
  id: StatId;
  // The card's eyebrow label, echoed at the top of the popover.
  title: string;
  // One-sentence plain-language definition of what the number measures.
  definition: string;
  // How it's actually derived from the store (the formula in words).
  computed: string;
  // Whether this metric reflects the SELECTED window or is all-time. Drives
  // the closing "Window" line the popover renders.
  scope: "window" | "lifetime";
};

// The catalogue. Order matches the cards left-to-right on /stats.
export const STAT_EXPLAINERS: Record<StatId, StatExplainer> = {
  lifetime: {
    id: "lifetime",
    title: "Lifetime shots",
    definition: "Every classification the service has ever stored, across all time.",
    computed:
      "A running count of shot rows in the store. The hint below shows how many of those landed inside the selected window.",
    scope: "lifetime",
  },
  mean_confidence: {
    id: "mean_confidence",
    title: "Mean confidence",
    definition:
      "The average top-class confidence the classifier reported for shots in this window.",
    computed:
      "Sum of each shot's winning-class score divided by the number of timed shots in the window. Higher is more decisive; a low mean means the model is hedging.",
    scope: "window",
  },
  p95_latency: {
    id: "p95_latency",
    title: "P95 latency",
    definition:
      "The 95th-percentile end-to-end classify time for shots in this window.",
    computed:
      "Shots in the window sorted by elapsed time; P95 is the value 95% of them came in under. The hint shows p50 (median) and p99 (tail) alongside it.",
    scope: "window",
  },
  corrections: {
    id: "corrections",
    title: "Corrections",
    definition:
      "How many shots in this window a human re-labelled away from the model's call.",
    computed:
      "A count of shots with a user-supplied correction. The rate beside it is corrections divided by total shots in the window -- a proxy for how often the model is wrong.",
    scope: "window",
  },
};

// Convenience accessor so the component doesn't index the record directly.
export function statExplainer(id: StatId): StatExplainer {
  return STAT_EXPLAINERS[id];
}

// Turn a window length in hours into the friendly phrasing the stats window
// buttons use (24h / 7d / 30d), falling back to a bare "Nh" / "Nd" form for
// any other value. Whole days collapse to "Nd"; sub-day spans stay in hours.
export function windowLabel(hours: number): string {
  if (!Number.isFinite(hours) || hours <= 0) return "this window";
  if (hours % 24 === 0) {
    const days = hours / 24;
    return days === 1 ? "24h" : `${days}d`;
  }
  return `${Math.round(hours)}h`;
}

// The closing line the popover shows: lifetime metrics say so explicitly;
// windowed metrics name the active window so the user knows the number moves
// when they switch 24h / 7d / 30d.
export function scopeNote(explainer: StatExplainer, hours: number): string {
  if (explainer.scope === "lifetime") {
    return "All-time figure -- unaffected by the window selector.";
  }
  return `Covers the last ${windowLabel(hours)}; changes when you switch windows.`;
}
