// Pure class-distribution tally for the /batch results (this tick). After a
// bulk run you could see each row's class in the table, but nothing told you
// the SHAPE of the batch -- "of these 50 frames, 22 were receipts and 9 were
// chats". This module rolls the settled rows into a sorted, count-desc
// breakdown the page renders as summary chips above the table. DOM-free so the
// tally + ordering is unit-testable; the component owns the chip markup.

import { LONG, type Category } from "./categories";

// The minimal row shape the tally reads. The page Row is a superset; only a
// successfully-classified row carries a `primary`, so unclassified / errored /
// pending rows are simply absent from the distribution.
export type ClassifiedRow = {
  status: string;
  primary?: Category;
};

export type ClassSlice = {
  category: Category;
  // Human label ("Receipt") so the chip reads without a second lookup.
  label: string;
  count: number;
  // Whole-percent share of the classified total, for the chip title.
  sharePct: number;
};

// Roll settled rows into a count-desc class distribution. Only rows that
// actually produced a class count -- a `done` row missing a primary (defensive)
// and every non-done row are skipped, so the shares always sum over real
// classifications. Ties break by the canonical category order via a stable
// sort on the input grouping. Returns [] when nothing has classified yet.
export function classDistribution(
  rows: readonly ClassifiedRow[] | null | undefined,
): ClassSlice[] {
  if (!Array.isArray(rows)) return [];
  const tally = new Map<Category, number>();
  for (const r of rows) {
    if (!r || r.status !== "done") continue;
    const cat = r.primary;
    if (cat == null) continue;
    tally.set(cat, (tally.get(cat) ?? 0) + 1);
  }
  const total = Array.from(tally.values()).reduce((a, b) => a + b, 0);
  if (total === 0) return [];
  // Insertion order of a Map is first-seen, which is the table order; a stable
  // count-desc sort therefore keeps same-count classes in the order they first
  // appeared -- deterministic without a secondary key.
  return Array.from(tally.entries())
    .map(([category, count]) => ({
      category,
      label: LONG[category],
      count,
      sharePct: Math.round((count / total) * 100),
    }))
    .sort((a, b) => b.count - a.count);
}

// Count of distinct classes present, for a "5 classes" header. Reads the
// distribution so it can't drift from the chips.
export function distinctClassCount(slices: readonly ClassSlice[]): number {
  return Array.isArray(slices) ? slices.length : 0;
}

// Chip title naming the share, e.g. "Receipt: 22 (44%)". Used as the hover /
// accessible description on each summary chip.
export function classSliceTitle(slice: ClassSlice): string {
  return `${slice.label}: ${slice.count} (${slice.sharePct}%)`;
}
