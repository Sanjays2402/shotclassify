// minConf threshold label helper (F156). The /shots confidence slider showed
// only a bare "80%" beside the track -- it read as "current value" with no hint
// it filters the list. This turns the whole-percent floor into the same shape
// the API + classifier use ("conf >= 0.80") so the control announces what it
// does, and a 0% floor reports "no floor" so we render nothing inert.
//
// Pure + DOM-free. The slider is whole percent (0..100, step 5); the API takes
// a 0..1 fraction. This converts once, clamped, so the label and the request
// can never disagree.

// True when the floor is actually constraining (0% is the inert default the
// slider rests at). Mirrors hasConfFloor in filter-summary so the chip and the
// breadcrumb agree on "is there a floor".
export function hasConfFloorPct(pct: number | null | undefined): pct is number {
  return typeof pct === "number" && Number.isFinite(pct) && pct > 0;
}

// "conf >= 0.80" inline label for an active floor, or null at 0 / non-finite
// so the caller renders nothing. The fraction is fixed to 2 decimals to match
// how confidence is quoted elsewhere; >100% clamps to 1.00.
export function confFloorLabel(pct: number | null | undefined): string | null {
  if (!hasConfFloorPct(pct)) return null;
  const frac = Math.min(100, pct) / 100;
  return `conf \u2265 ${frac.toFixed(2)}`;
}

// The bare slider readout: the active threshold when narrowed, else "any" so
// the resting state reads as "no floor" rather than "0%". Glanceable next to
// the track.
export function confFloorReadout(pct: number | null | undefined): string {
  const label = confFloorLabel(pct);
  return label ?? "any";
}
