// Pure helpers for the /digest "By category" share bars (F154 follow-up). The
// category list shows a count + mean confidence but nothing visual: a class
// that's 60% of your volume reads the same as one that's 5%. This module turns
// each category's count into a share-of-total percent + bar width, so the page
// renders a thin proportional bar behind each row and the eye finds the leaders
// instantly. DOM-free so it's unit-testable; the page just maps the result.

export type CategoryShareInput = {
  category: string;
  label: string;
  count: number;
};

export type CategoryShare = {
  category: string;
  label: string;
  count: number;
  // 0..1 share of the summed counts. 0 when total is 0.
  share: number;
  // Whole-percent share for the readout, e.g. 42. Sums close to 100 (rounding).
  pct: number;
  // Bar width as a CSS percent string, never narrower than a sliver so a tiny
  // nonzero class is still visible. "0%" only for a genuine zero.
  widthPct: string;
};

// Total of the counts, defensively ignoring non-finite / negative rows.
export function totalCategoryCount(rows: readonly CategoryShareInput[] | null | undefined): number {
  if (!Array.isArray(rows)) return 0;
  let t = 0;
  for (const r of rows) {
    if (r && Number.isFinite(r.count) && r.count > 0) t += Math.trunc(r.count);
  }
  return t;
}

// Build the share rows, preserving input order (the page sorts upstream). A
// zero / empty total yields zero shares so no bar lies about dominance.
export function categoryShares(
  rows: readonly CategoryShareInput[] | null | undefined,
): CategoryShare[] {
  if (!Array.isArray(rows)) return [];
  const total = totalCategoryCount(rows);
  return rows.map((r) => {
    const count = r && Number.isFinite(r.count) && r.count > 0 ? Math.trunc(r.count) : 0;
    const share = total > 0 ? count / total : 0;
    const pct = Math.round(share * 100);
    // Floor a nonzero bar at 4% so a 1% class is still a visible sliver.
    const w = count > 0 ? Math.max(4, share * 100) : 0;
    return {
      category: r.category,
      label: r.label,
      count,
      share,
      pct,
      widthPct: count > 0 ? `${w.toFixed(1)}%` : "0%",
    };
  });
}

// "42% of shots" caption for a single row's title/aria, or "no shots" at zero.
export function categoryShareLabel(share: CategoryShare | null | undefined): string {
  if (!share || share.count <= 0) return "no shots";
  return `${share.pct}% of shots`;
}
