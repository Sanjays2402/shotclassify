// Per-row "calls vs fleet max" mini-bar geometry for the /keys table (F152).
// The usage column showed a bare integer, so a 12-call key and a 12,000-call
// key looked equally heavy until you read the digits. This rolls each row's
// usage into a width fraction against the busiest key in the fleet, plus a
// share-of-total, so a thin bar under the count makes relative volume legible
// at a glance. Pure + DOM-free: the component renders a tested view-model.

type CallRow = { usage_count?: number | null };

// Coerce a row's usage into a clean non-negative integer (non-finite /
// negative -> 0, fractional truncates). The fleet max + share both build on
// this so a single row and the bar widths can never disagree.
export function callCount(row: CallRow | null | undefined): number {
  const n = Number(row?.usage_count);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0;
}

// The busiest key's count across the fleet, floored at 1 so dividing by it is
// always safe (an all-zero fleet yields max 1 and every bar reads empty).
export function fleetMaxCalls(rows: readonly CallRow[] | null | undefined): number {
  if (!Array.isArray(rows)) return 1;
  let max = 0;
  for (const r of rows) {
    const c = callCount(r);
    if (c > max) max = c;
  }
  return Math.max(1, max);
}

export type CallBar = {
  count: number;
  // 0..1 width relative to the fleet's busiest key.
  ratio: number;
  // Width as a CSS percent string, min 2% when there's any traffic so a tiny
  // bar is still visible, 0% when the key has never been called.
  widthPct: string;
  // True for the fleet leader (count === max and max > 0) so the row can be
  // accented. Ties all read as busiest.
  isBusiest: boolean;
};

// View-model for one row's bar. `max` is the fleet max (pass fleetMaxCalls);
// keeping it a param means the table computes it once and threads it to every
// row rather than each row re-scanning. A zero-call key reads 0% / not busiest.
export function callBar(count: number, max: number): CallBar {
  const c = Number.isFinite(count) && count > 0 ? Math.trunc(count) : 0;
  const m = Number.isFinite(max) && max > 0 ? Math.trunc(max) : 1;
  const ratio = Math.min(1, c / m);
  const isBusiest = c > 0 && c >= m;
  const widthPct = c <= 0 ? "0%" : `${Math.max(2, Math.round(ratio * 100))}%`;
  return { count: c, ratio, widthPct, isBusiest };
}

// One-line title for the bar's hover: "1,204 calls (38% of fleet peak)".
// Reports "never called" at zero. Reuses the shared count noun shape.
export function callBarTitle(count: number, max: number): string {
  const bar = callBar(count, max);
  if (bar.count <= 0) return "Never called";
  const pct = Math.round(bar.ratio * 100);
  const noun = bar.count === 1 ? "call" : "calls";
  return `${bar.count.toLocaleString()} ${noun} (${pct}% of fleet peak)`;
}
