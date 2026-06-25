// Pure helpers for the <Skeleton> loading primitive. Kept DOM-free so the
// variant -> dimensions mapping and the deterministic "ragged line" widths
// are unit-testable. The codebase rolls its own `h-8 animate-pulse` divs on
// every page that loads async data (/shots, /webhooks, /notifications, admin);
// this centralises the shimmer so loading states look identical everywhere.

export type SkeletonVariant = "text" | "chip" | "panel-row" | "block" | "circle";

export type SkeletonShape = {
  // CSS height. Numbers become px; strings pass through (e.g. "100%").
  height: string;
  // CSS width. Same coercion rules.
  width: string;
  // Border radius in px. Circles get a big radius so they render round.
  radius: number;
};

// Per-variant default geometry. `text` is a single type line, `chip` mimics a
// scorebug chip, `panel-row` is a full table/list row, `block` is a generic
// rectangle, `circle` is an avatar / icon well.
export const VARIANT_SHAPES: Record<SkeletonVariant, SkeletonShape> = {
  text: { height: "0.8em", width: "100%", radius: 3 },
  chip: { height: "20px", width: "84px", radius: 2 },
  "panel-row": { height: "32px", width: "100%", radius: 4 },
  block: { height: "100%", width: "100%", radius: 6 },
  circle: { height: "40px", width: "40px", radius: 9999 },
};

// Coerce a number to a px string; leave strings untouched. Lets callers pass
// either `width={120}` or `width="60%"`.
export function toCssSize(v: number | string | undefined, fallback: string): string {
  if (v === undefined) return fallback;
  if (typeof v === "number") return `${v}px`;
  return v;
}

// Resolve the final shape for a variant given optional caller overrides.
export function resolveShape(
  variant: SkeletonVariant,
  overrides?: { width?: number | string; height?: number | string; radius?: number },
): SkeletonShape {
  const base = VARIANT_SHAPES[variant];
  return {
    height: toCssSize(overrides?.height, base.height),
    width: toCssSize(overrides?.width, base.width),
    radius:
      typeof overrides?.radius === "number" ? overrides.radius : base.radius,
  };
}

// Deterministic, seeded "ragged" widths so a multi-line text skeleton doesn't
// render as a perfect rectangle (which reads as a solid block, not text).
// Pure + seeded so SSR and client agree -> no hydration mismatch. Widths land
// in the 62%-100% band; the LAST line is always the shortest (like a real
// paragraph's final line). Returns percentage strings.
export function raggedWidths(count: number, seed = 1): string[] {
  if (count <= 0) return [];
  if (count === 1) return ["100%"];
  const out: string[] = [];
  let s = (seed * 2654435761) >>> 0;
  for (let i = 0; i < count; i++) {
    // xorshift step for a stable pseudo-random in [0,1).
    s ^= s << 13;
    s >>>= 0;
    s ^= s >> 17;
    s ^= s << 5;
    s >>>= 0;
    const r = s / 0xffffffff;
    const pct = Math.round(62 + r * 33); // 62..95
    out.push(`${pct}%`);
  }
  // Force the final line shorter so it reads like end-of-paragraph.
  out[out.length - 1] = "48%";
  return out;
}
