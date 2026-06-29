// Pure progress math for the /batch bulk-classify page (this tick). A running
// batch surfaced only four count pills (N files / N done / N errors / N
// pending) -- there was no at-a-glance sense of how far along a 200-image run
// was. This module turns the row tallies into a determinate progress reading
// (processed / total, a clamped percent, and a human label) so the page can
// draw a real progress bar. DOM-free so the arithmetic is unit-testable; the
// component owns the bar element.

export type BatchCounts = {
  total: number;
  done: number;
  err: number;
  pending: number;
};

// A row is "settled" once it has either succeeded or errored -- both are
// terminal, so progress counts them together. Pending + running rows are the
// remaining work.
export function settledCount(c: BatchCounts): number {
  const done = Math.max(0, Math.trunc(num(c.done)));
  const err = Math.max(0, Math.trunc(num(c.err)));
  return done + err;
}

// Completion percent in 0..100, rounded to a whole number. Zero total yields 0
// (an empty batch is "not started", not "complete") so the bar reads empty
// rather than full before any files are added. Settled is clamped to total so
// a transient over-count can never print 110%.
export function progressPercent(c: BatchCounts): number {
  const total = Math.max(0, Math.trunc(num(c.total)));
  if (total <= 0) return 0;
  const settled = Math.min(settledCount(c), total);
  return Math.round((settled / total) * 100);
}

// True once every row has settled (and there is at least one row). The page
// flips the bar to a "done" treatment and the run button to "All done" here.
export function isBatchComplete(c: BatchCounts): boolean {
  const total = Math.max(0, Math.trunc(num(c.total)));
  if (total <= 0) return false;
  return settledCount(c) >= total;
}

// Short status line beneath the bar: "12 of 50 processed" mid-run, "50
// processed" when complete (no redundant "50 of 50"), and "" for an empty
// batch so the caller can hide the label entirely. Pluralises naturally and
// names errors when any settled row failed so a partial failure is visible
// without scanning the table.
export function progressLabel(c: BatchCounts): string {
  const total = Math.max(0, Math.trunc(num(c.total)));
  if (total <= 0) return "";
  const settled = Math.min(settledCount(c), total);
  const err = Math.max(0, Math.trunc(num(c.err)));
  const head = isBatchComplete(c)
    ? `${total} processed`
    : `${settled} of ${total} processed`;
  if (err > 0) {
    return `${head} \u00b7 ${err} ${err === 1 ? "error" : "errors"}`;
  }
  return head;
}

// Coerce a possibly-NaN/undefined count to a finite number; non-finite -> 0 so
// a half-initialised tally can't poison the arithmetic.
function num(n: number): number {
  return Number.isFinite(n) ? n : 0;
}
