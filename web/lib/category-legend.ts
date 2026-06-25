// Pure helpers for the per-category legend hover popover on /stats (F14).
// Given the per-class rollup the stats aggregate already returns, build the
// small summary a hover popover shows for one category: its count, share of
// the total, mean confidence, and the /shots deep-link. DOM-free so the
// formatting + share math is unit-testable; the popover component is a thin
// renderer over this.

import { LONG, type Category } from "./categories";

// One row of the stats aggregate's per_class array.
export type PerClassRow = {
  category: Category;
  count: number;
  mean_confidence: number;
};

export type CategoryLegendSummary = {
  category: Category;
  // Human label, e.g. "Code snippet".
  label: string;
  count: number;
  // Share of the whole window's volume as a 0..1 fraction.
  share: number;
  // Pre-formatted "12.3%" share string.
  sharePct: string;
  // Mean confidence as a 0..1 fraction, clamped.
  meanConfidence: number;
  // Pre-formatted "87%" mean-confidence string.
  meanConfidencePct: string;
  // Deep link into the shots table pre-filtered to this class.
  shotsHref: string;
};

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

function pctString(fraction: number, digits = 0): string {
  return `${(clamp01(fraction) * 100).toFixed(digits)}%`;
}

// Compute the total count across every per-class row. Defensive against
// missing / non-numeric counts so a malformed row can't poison the share
// denominator.
export function totalCount(rows: readonly PerClassRow[] | null | undefined): number {
  if (!Array.isArray(rows)) return 0;
  return rows.reduce(
    (sum, r) => sum + (Number.isFinite(r?.count) && r.count > 0 ? r.count : 0),
    0,
  );
}

// Build the popover summary for a single category. The total is passed in
// (the caller computes it once via totalCount) so each chip doesn't re-sum
// the array. A zero total yields a 0% share rather than NaN.
export function categoryLegendSummary(
  row: PerClassRow,
  total: number,
): CategoryLegendSummary {
  const count = Number.isFinite(row.count) && row.count > 0 ? row.count : 0;
  const share = total > 0 ? count / total : 0;
  const meanConfidence = clamp01(row.mean_confidence);
  return {
    category: row.category,
    label: LONG[row.category] ?? String(row.category),
    count,
    share,
    sharePct: pctString(share, 1),
    meanConfidence,
    meanConfidencePct: pctString(meanConfidence, 0),
    shotsHref: `/shots?category=${encodeURIComponent(row.category)}`,
  };
}

// Convenience: build summaries for an entire per_class array in one call,
// sharing the total. Order is preserved from the input.
export function categoryLegendSummaries(
  rows: readonly PerClassRow[] | null | undefined,
): CategoryLegendSummary[] {
  if (!Array.isArray(rows) || rows.length === 0) return [];
  const total = totalCount(rows);
  return rows.map((r) => categoryLegendSummary(r, total));
}
