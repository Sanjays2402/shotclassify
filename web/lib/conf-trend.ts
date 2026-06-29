// Confidence-trend summary for the /stats Box-score page (F65, the long-open
// F16/F27/F41/F54). The aggregate `hourly` buckets now carry a per-bucket
// mean_confidence, so we can finally describe the calibration trend across the
// window honestly. This module is the DOM-free contract: turn the hourly
// series into first/last/delta/peak numbers plus a percent-point delta and an
// arrow glyph, so the page renders a thin chip and tests pin the wording.
//
// All confidences are 0..1 fractions on the wire; we surface whole-percent
// readouts ("78%") and a percent-point delta ("+2.4pts") to match the KPI
// cards. The stroke colour comes from chart-theme's deltaStroke so a rising
// trend reads green and a falling one red, agreeing with the rest of the page.

export type ConfBucket = {
  // Bucket count -- zero-count buckets carry no real confidence and are skipped
  // so a quiet hour can't drag the trend to a misleading 0.
  count: number;
  mean_confidence: number;
};

export type ConfTrend = {
  // Whole-percent first / last readings across the populated buckets.
  firstPct: number;
  lastPct: number;
  // Percent-point delta (last - first), one decimal, e.g. +2.4 / -1.0 / 0.0.
  deltaPts: number;
  // Direction arrow for the chip: up / down / flat. Flat when |delta| rounds
  // to 0.0 so a hairline wobble doesn't claim a trend.
  arrow: "up" | "down" | "flat";
  // Peak whole-percent confidence seen in the window (for the chip's title).
  peakPct: number;
  // Buckets that actually contributed (count > 0). The chip hides below 2.
  populated: number;
};

// True when there are at least two populated buckets to compare -- a single
// hour (or none) has no trend, so the chip should hide rather than print 0.
export function hasConfTrend(buckets: readonly ConfBucket[] | null | undefined): boolean {
  if (!Array.isArray(buckets)) return false;
  let n = 0;
  for (const b of buckets) {
    if (b && Number.isFinite(b.count) && b.count > 0) n += 1;
    if (n >= 2) return true;
  }
  return false;
}

// Build the trend summary, or null when there's nothing honest to show (fewer
// than two populated buckets). Confidences clamp to 0..1 before display so a
// bad sample can't print 142%. The percent-point delta is rounded to 1dp.
export function confTrend(
  buckets: readonly ConfBucket[] | null | undefined,
): ConfTrend | null {
  if (!Array.isArray(buckets)) return null;
  const live = buckets.filter(
    (b) => b && Number.isFinite(b.count) && b.count > 0 && Number.isFinite(b.mean_confidence),
  );
  if (live.length < 2) return null;
  const clamp = (n: number) => Math.min(1, Math.max(0, n));
  const firstPct = Math.round(clamp(live[0].mean_confidence) * 100);
  const lastPct = Math.round(clamp(live[live.length - 1].mean_confidence) * 100);
  const peakPct = Math.round(
    clamp(Math.max(...live.map((b) => b.mean_confidence))) * 100,
  );
  const deltaPts = +(lastPct - firstPct).toFixed(1);
  const arrow = deltaPts > 0 ? "up" : deltaPts < 0 ? "down" : "flat";
  return { firstPct, lastPct, deltaPts, arrow, peakPct, populated: live.length };
}

// Signed percent-point label for the chip, e.g. "+2.4pts" / "-1.0pts" / "0pts".
// Flat reports a bare "0pts" so it doesn't pretend to a direction.
export function confTrendDeltaLabel(t: ConfTrend | null | undefined): string | null {
  if (!t) return null;
  if (t.deltaPts === 0) return "0pts";
  const sign = t.deltaPts > 0 ? "+" : "";
  return `${sign}${t.deltaPts.toFixed(1)}pts`;
}
