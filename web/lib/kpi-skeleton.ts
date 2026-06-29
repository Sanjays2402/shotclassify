// KPI-card skeleton helpers for /stats (F146). The four box-score cards
// (Lifetime shots / Mean confidence / P95 / Corrections) popped in fully
// formed once the first aggregate resolved while the charts already showed
// chalk skeletons -- a small jolt at the top of the page. This drives a
// matching set of skeleton cards during the same `busy` window the charts
// use, so the whole page settles together.
//
// Pure + DOM-free: just the count + a stable key list so the placeholder grid
// renders the same footprint as the real four-card row (grid-cols-2 / md:4).

// How many KPI cards the box-score row shows. Mirrors the four <Stat> cards so
// the skeleton occupies the exact same 2x2 / 1x4 grid before data lands.
export const KPI_CARD_COUNT = 4;

// Stable keys for the placeholder cards so React reconciles them cleanly and
// callers can `.map` without an index key. Length === KPI_CARD_COUNT.
export function kpiSkeletonKeys(count: number = KPI_CARD_COUNT): string[] {
  const n = Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
  return Array.from({ length: n }, (_, i) => `kpi-skeleton-${i}`);
}

// Whether to show the KPI skeleton row instead of the real cards. Reuses the
// same boolean the charts read (chartsBusy) so the cards + charts skeleton and
// reveal in lockstep -- no half-loaded page.
export function showKpiSkeleton(busy: boolean): boolean {
  return busy === true;
}
