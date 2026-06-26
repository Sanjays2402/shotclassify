// Increase-detection for the live ticker's count pulse (F76). The 24h total
// (and per-class counts) revalidate every 30s; when a number ticks UP we want
// a brief cue-yellow glow so a watcher notices live activity without staring.
// The detection logic is pure + DOM-free so it's unit-testable; the component
// wraps it with a usePrevious-style ref + a transient CSS class.

// True when `next` is a strictly greater finite number than `prev`. A first
// observation (prev undefined / null) is NOT a pulse -- we only glow on an
// actual increase, never on initial paint. Decreases and equal values don't
// pulse either (a count going down, e.g. after a correction reclassifies, is
// not "new activity" to celebrate). Non-finite inputs are treated as "no
// pulse" so a NaN from a malformed payload can't flicker the row.
export function didIncrease(
  prev: number | null | undefined,
  next: number,
): boolean {
  if (typeof prev !== "number" || !Number.isFinite(prev)) return false;
  if (!Number.isFinite(next)) return false;
  return next > prev;
}

// Given the previous and next per-key counts, return the set of keys whose
// count increased. Used to glow only the classes that actually moved, not the
// whole row, on a revalidate. Keys absent from `prev` are first-observations
// and never pulse (same rule as didIncrease). Pure -- the caller supplies both
// maps.
export function increasedKeys(
  prev: Readonly<Record<string, number>> | null | undefined,
  next: Readonly<Record<string, number>>,
): string[] {
  const out: string[] = [];
  if (!prev) return out;
  for (const k of Object.keys(next)) {
    if (didIncrease(prev[k], next[k])) out.push(k);
  }
  return out;
}
