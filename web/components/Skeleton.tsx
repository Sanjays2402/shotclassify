"use client";

// <Skeleton> + <SkeletonText> + <SkeletonRows> -- the canonical loading
// shimmer primitives. Replaces ad-hoc `h-8 animate-pulse` divs scattered
// across pages so every loading state pulses identically and respects
// reduced-motion (the shimmer uses the shared .sc-skeleton class in
// globals.css which disables animation under prefers-reduced-motion).

import { resolveShape, raggedWidths, type SkeletonVariant } from "@/lib/skeleton";

export type SkeletonProps = {
  variant?: SkeletonVariant;
  width?: number | string;
  height?: number | string;
  radius?: number;
  className?: string;
  // Decorative by default -- screen readers should hear the page's own
  // "Loading..." status region instead of N shimmer cells.
  "aria-hidden"?: boolean;
};

export function Skeleton({
  variant = "block",
  width,
  height,
  radius,
  className,
}: SkeletonProps) {
  const shape = resolveShape(variant, { width, height, radius });
  return (
    <span
      className={["sc-skeleton", className].filter(Boolean).join(" ")}
      style={{
        display: "block",
        width: shape.width,
        height: shape.height,
        borderRadius: shape.radius,
      }}
      aria-hidden
      data-testid="skeleton"
      data-variant={variant}
    />
  );
}

// A multi-line text block with seeded-ragged widths so it reads like a
// paragraph rather than a solid bar. `seed` keeps SSR + client agreeing.
export function SkeletonText({
  lines = 3,
  seed = 1,
  className,
  gap = 6,
}: {
  lines?: number;
  seed?: number;
  className?: string;
  gap?: number;
}) {
  const widths = raggedWidths(lines, seed);
  return (
    <span
      className={["flex flex-col", className].filter(Boolean).join(" ")}
      style={{ gap }}
      aria-hidden
      data-testid="skeleton-text"
    >
      {widths.map((w, i) => (
        <Skeleton key={i} variant="text" width={w} />
      ))}
    </span>
  );
}

// A stack of full-width panel rows -- the shape every table/list loading
// state wants. Wrap in the page's `aria-label="Loading ..."` region.
export function SkeletonRows({
  rows = 8,
  gap = 8,
  className,
}: {
  rows?: number;
  gap?: number;
  className?: string;
}) {
  return (
    <div
      className={["flex flex-col", className].filter(Boolean).join(" ")}
      style={{ gap }}
      aria-hidden
      data-testid="skeleton-rows"
    >
      {Array.from({ length: Math.max(0, rows) }).map((_, i) => (
        <Skeleton key={i} variant="panel-row" />
      ))}
    </div>
  );
}

export default Skeleton;
