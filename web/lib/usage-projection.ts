// Pure month-end spend projection for the /usage quota meter (F166). The meter
// shows what you've USED so far this period, but not where you're HEADING --
// at the current pace, will you cruise in under the cap or blow through it on
// the 22nd? This module linear-extrapolates the run rate (used / fraction of
// the period elapsed) to a projected period-end total, and reports whether
// that projection clears the limit and (if so) roughly when. DOM-free so the
// arithmetic is unit-testable; the component renders a caption beneath the bar.
//
// Honest projection: it's a straight-line extrapolation of the average daily
// rate, NOT a forecast -- a quiet weekend or a Monday spike will move it. The
// caption wording says "on pace", so we never over-claim precision.

export type ProjectionInput = {
  // ISO timestamps bounding the billing period.
  periodStart: string | number | null | undefined;
  periodEnd: string | number | null | undefined;
  // Classifications used so far this period.
  used: number;
  // The plan ceiling for the period.
  limit: number;
  // "Now" as epoch ms -- injected so tests are deterministic. The component
  // passes Date.now().
  now: number;
};

export type Projection = {
  // Whether we could compute a projection at all. False before any time has
  // elapsed (can't infer a rate from a zero-width window) or on bad input.
  ok: boolean;
  // Fraction of the period elapsed, 0..1.
  elapsedFraction: number;
  // Projected total spend by period end, rounded. null when !ok.
  projectedTotal: number | null;
  // True when the projected total exceeds the limit at the current pace.
  willExceed: boolean;
  // Projected fraction of the limit (projectedTotal / limit), e.g. 1.3 = 130%.
  // null when !ok or the limit is non-positive.
  projectedPercentOfLimit: number | null;
};

function toMs(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const t = Date.parse(v.trim());
  return Number.isFinite(t) ? t : null;
}

function nonNegInt(n: number): number {
  return Number.isFinite(n) ? Math.max(0, n) : 0;
}

// Compute the straight-line projection. Clamps `now` into the period window so
// a clock just past period-end projects the final total rather than dividing
// by a >1 elapsed fraction. Returns an !ok shell when the period is degenerate
// (no width) or the timestamps don't parse.
export function projectUsage(input: ProjectionInput): Projection {
  const shell: Projection = {
    ok: false,
    elapsedFraction: 0,
    projectedTotal: null,
    willExceed: false,
    projectedPercentOfLimit: null,
  };
  const start = toMs(input.periodStart);
  const end = toMs(input.periodEnd);
  const now = toMs(input.now);
  if (start === null || end === null || now === null) return shell;
  const span = end - start;
  if (span <= 0) return shell;

  // Clamp now into [start, end]. Before start -> no elapsed time yet.
  const clampedNow = Math.min(end, Math.max(start, now));
  const elapsed = clampedNow - start;
  const elapsedFraction = elapsed / span;
  if (elapsedFraction <= 0) return shell;

  const used = nonNegInt(input.used);
  // Straight-line: total = used / fractionElapsed. Capped extrapolation never
  // projects LESS than what's already spent (a near-complete period whose
  // fraction rounds high can't under-shoot the real used count).
  const projectedTotal = Math.max(used, Math.round(used / elapsedFraction));
  const limit = input.limit;
  const limitPositive = Number.isFinite(limit) && limit > 0;
  const projectedPercentOfLimit = limitPositive ? projectedTotal / limit : null;
  const willExceed = limitPositive ? projectedTotal > limit : false;

  return {
    ok: true,
    elapsedFraction,
    projectedTotal,
    willExceed,
    projectedPercentOfLimit,
  };
}

// One-line caption for beneath the bar, e.g.
//   "On pace for ~8,400 of 10,000 by Jun 30."  (under)
//   "On pace to exceed the limit (~12,300) before Jun 30."  (over)
// Returns "" when there's nothing trustworthy to say so the caller hides it.
// `endLabel` is a pre-formatted short date the component already has (we don't
// re-format dates here -- that's the date-format lib's job and the meter's
// fmtDate). Numbers are grouped for readability.
export function projectionCaption(
  p: Projection,
  limit: number,
  endLabel: string,
): string {
  if (!p.ok || p.projectedTotal === null) return "";
  const total = p.projectedTotal.toLocaleString();
  if (p.willExceed) {
    return `On pace to exceed the limit (~${total}) before ${endLabel}.`;
  }
  const cap = Number.isFinite(limit) ? limit.toLocaleString() : "the limit";
  return `On pace for ~${total} of ${cap} by ${endLabel}.`;
}
