// Diverging confidence-gap geometry for the /compare delta bar (F161). The
// DeltaBar already prints a "Confidence gap" Stat -- a single number like
// "4.2 pts" -- but a bare number doesn't read at a glance: is B a hair ahead
// or in a different league? This module turns the two confidences into a
// tug-of-war geometry the page draws as a small diverging bar: A's score grows
// left of a centre axis, B's grows right, and the eye sees which bar is longer
// (i.e. the gap) without parsing digits. DOM-free so the arithmetic is
// unit-testable; the component owns the bar markup.
//
// Honest by construction: each side's fill is its OWN clamped confidence, so
// the visual difference in the two bar lengths IS the real gap -- nothing is
// scaled or exaggerated to manufacture contrast.

export type GapGeometry = {
  // A's confidence as a 0..1 fraction of its (left) half, clamped.
  aFill: number;
  // B's confidence as a 0..1 fraction of its (right) half, clamped.
  bFill: number;
  // Signed gap in percentage points, b - a, rounded to one decimal. Positive
  // means B is more confident; negative means A is.
  deltaPts: number;
  // Magnitude of the gap in points (|deltaPts|), one decimal -- the number the
  // Stat already shows, kept here so the label and bar can't drift.
  absPts: number;
  // Which side is ahead. "tie" when the (rounded-to-1dp) gap is zero, so a
  // sub-0.05pt jitter doesn't claim a winner.
  winner: "a" | "b" | "tie";
};

// Clamp an arbitrary value to a 0..1 confidence fraction; non-finite -> 0 so a
// half-loaded panel can't poison the geometry.
function clamp01(n: number | null | undefined): number {
  if (typeof n !== "number" || !Number.isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

// Round to one decimal place, killing -0 so a zero gap never prints "-0.0".
function round1(n: number): number {
  const r = Math.round(n * 10) / 10;
  return r === 0 ? 0 : r;
}

// Build the diverging geometry from the two side confidences (0..1 fractions).
// The winner is decided on the ROUNDED gap so the bar's accent and the printed
// "X pts" never disagree -- if it shows 0.0 pts it's a tie, full stop.
export function confidenceGap(
  aConf: number | null | undefined,
  bConf: number | null | undefined,
): GapGeometry {
  const aFill = clamp01(aConf);
  const bFill = clamp01(bConf);
  const deltaPts = round1((bFill - aFill) * 100);
  const absPts = Math.abs(deltaPts);
  const winner: GapGeometry["winner"] =
    deltaPts > 0 ? "b" : deltaPts < 0 ? "a" : "tie";
  return { aFill, bFill, deltaPts, absPts, winner };
}

// Accessible one-line description of the gap, e.g. "Shot B is 4.2 points more
// confident" / "Both shots are equally confident". Drives the bar's aria-label
// so the diverging visual isn't mute to assistive tech.
export function gapAriaLabel(g: GapGeometry): string {
  if (g.winner === "tie") return "Both shots are equally confident";
  const side = g.winner === "a" ? "Shot A" : "Shot B";
  const pts = g.absPts === 1 ? "point" : "points";
  return `${side} is ${g.absPts} ${pts} more confident`;
}
