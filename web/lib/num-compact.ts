// Compact number formatter for KPI cards, the live ticker, and quota meters.
// Big totals rendered through toLocaleString grow to "12,345,678" -- nine glyphs
// that overflow the narrow KPI tiles and the ticker row, forcing a wrap. This
// abbreviates to "12.3M" with a tight, glanceable footprint while a tooltip /
// aria-label can still carry the exact figure (use full() for that). Pure +
// DOM-free so it's unit-testable and every count surface agrees on rounding.

// Suffix steps. Each is 1000x the previous; we stop at trillions which covers
// any plausible classification count. Stored ascending so we can walk down.
const STEPS: ReadonlyArray<{ value: number; suffix: string }> = [
  { value: 1e12, suffix: "T" },
  { value: 1e9, suffix: "B" },
  { value: 1e6, suffix: "M" },
  { value: 1e3, suffix: "K" },
];

// "12.3K" / "1.2M" / "987" compact label. < 1000 stays exact (no suffix). At or
// above 1000 we pick the largest step and keep one decimal, trimming a trailing
// ".0" so round thousands read "12K" not "12.0K". Negatives keep their sign;
// non-finite / nullish falls back to "0" so a tile never prints "NaN". One
// decimal caps width at five glyphs ("12.3M") -- the whole point.
export function compactNumber(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "0";
  const neg = n < 0;
  const abs = Math.abs(n);
  if (abs < 1000) return (neg ? -Math.trunc(abs) : Math.trunc(abs)).toString();
  for (const step of STEPS) {
    if (abs >= step.value) {
      const scaled = abs / step.value;
      // One decimal, then drop a redundant ".0".
      const body = scaled.toFixed(1).replace(/\.0$/, "");
      return `${neg ? "-" : ""}${body}${step.suffix}`;
    }
  }
  return (neg ? -Math.trunc(abs) : Math.trunc(abs)).toString();
}

// Exact grouped figure for the tooltip / aria-label that pairs with the compact
// visible text, so the abbreviation never hides the real number from assistive
// tech or a curious hover. Nullish / non-finite -> "0".
export function fullNumber(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "0";
  return Math.trunc(n).toLocaleString();
}

// True when abbreviating actually changes the rendering, i.e. the value is big
// enough to gain a suffix. The caller can use this to attach the exact-figure
// title ONLY when it differs from the visible text, avoiding a redundant
// "1,234 / 1,234" tooltip.
export function isCompacted(n: number | null | undefined): boolean {
  return typeof n === "number" && Number.isFinite(n) && Math.abs(n) >= 1000;
}
