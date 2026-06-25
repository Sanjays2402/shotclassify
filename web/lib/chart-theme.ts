// Recharts theming tokens that respond to the active app theme (light /
// dim). Every recharts surface in the app hard-codes light-mode strokes
// like `rgba(11,15,12,0.4)` for axes and grids -- near-black lines that all
// but vanish on dim mode's dark panels. This module centralises the
// theme-aware token set so each chart can pull stroke / grid / tooltip /
// cursor values that read correctly under both palettes.
//
// Pure + DOM-free so the token math is unit-testable; the matching
// useChartTheme() hook (components/useChartTheme.ts) reads the live
// data-theme attribute and feeds the resolved theme in here.

import type { ResolvedTheme } from "./theme";

// recharts' Tooltip contentStyle is a plain CSSProperties bag. We keep the
// broadcast "dark card" aesthetic in BOTH themes -- a dark ink card with
// chalk text reads well over light and dim chart areas alike and stays on
// brand. Hard-coded true-ink / true-chalk hexes (not the CSS vars, which
// invert under dim) so the tooltip never flips to light-on-light.
export type ChartTooltipStyle = {
  background: string;
  border: string;
  borderRadius: number;
  color: string;
  fontFamily: string;
  fontSize: number;
};

export type ChartTheme = {
  // Axis line + tick-line stroke colour.
  axisStroke: string;
  // A fainter axis stroke for secondary / right-hand axes.
  axisStrokeFaint: string;
  // Cartesian grid line stroke.
  gridStroke: string;
  // Axis tick label fill (the numbers / category names).
  tickFill: string;
  // Hover cursor highlight fill (the band behind the hovered bar).
  cursorFill: string;
  // Reference-line stroke (e.g. the y=x diagonal on the calibration chart).
  referenceStroke: string;
  // Delta tokens for trend / sparkline charts that encode direction. A
  // rising series (e.g. mean-confidence climbing) strokes green; a falling
  // one strokes red; the y=0 baseline gets a neutral zeroLine. The *Fill
  // pair are the faint area-fill companions (use under an <Area>). These
  // stay legible under both the light and dim palettes -- the dim variants
  // are lightened/brightened so they don't sink into the dark panel.
  positiveStroke: string;
  negativeStroke: string;
  positiveFill: string;
  negativeFill: string;
  zeroLine: string;
  // Tooltip card style bag, ready to spread onto <Tooltip contentStyle>.
  tooltip: ChartTooltipStyle;
};

const TOOLTIP_BASE = {
  background: "#0B0F0C", // true ink -- stays dark under both themes
  border: "1px solid #000",
  borderRadius: 3,
  color: "#F2EBD8", // true chalk -- stays light under both themes
  fontFamily: "var(--font-mono)",
  fontSize: 11,
} as const satisfies ChartTooltipStyle;

const LIGHT: ChartTheme = {
  axisStroke: "rgba(11,15,12,0.40)",
  axisStrokeFaint: "rgba(11,15,12,0.30)",
  gridStroke: "rgba(11,15,12,0.08)",
  tickFill: "rgba(11,15,12,0.65)",
  cursorFill: "rgba(14,92,58,0.06)",
  referenceStroke: "rgba(11,15,12,0.35)",
  positiveStroke: "#0E5C3A", // felt green -- a rising trend reads "good"
  negativeStroke: "#B91C1C", // umpire red -- a falling trend reads "watch"
  positiveFill: "rgba(14,92,58,0.14)",
  negativeFill: "rgba(185,28,28,0.12)",
  zeroLine: "rgba(11,15,12,0.22)",
  tooltip: { ...TOOLTIP_BASE },
};

const DIM: ChartTheme = {
  axisStroke: "rgba(232,226,204,0.38)",
  axisStrokeFaint: "rgba(232,226,204,0.24)",
  gridStroke: "rgba(232,226,204,0.12)",
  tickFill: "rgba(232,226,204,0.62)",
  cursorFill: "rgba(20,112,74,0.18)",
  referenceStroke: "rgba(232,226,204,0.32)",
  positiveStroke: "#3FBF82", // brightened green so it lifts off the dark panel
  negativeStroke: "#F2696B", // brightened red, same reason
  positiveFill: "rgba(63,191,130,0.20)",
  negativeFill: "rgba(242,105,107,0.18)",
  zeroLine: "rgba(232,226,204,0.28)",
  tooltip: { ...TOOLTIP_BASE },
};

// Resolve the full token set for a theme. Defaults to the light palette for
// any unknown value so a caller that hasn't mounted yet still renders
// something sensible (matches the historical hard-coded look).
export function chartTheme(resolved: ResolvedTheme | string | null | undefined): ChartTheme {
  return resolved === "dim" ? DIM : LIGHT;
}

// Convenience: the recharts `tick` prop wants `{ fontSize, fontFamily,
// fill }`. Build it from the theme so every axis shares one definition.
export function axisTick(theme: ChartTheme, fontSize = 10): {
  fontSize: number;
  fontFamily: string;
  fill: string;
} {
  return {
    fontSize,
    fontFamily: "var(--font-mono)",
    fill: theme.tickFill,
  };
}

// Pick the directional stroke for a signed delta. A positive (or zero,
// treated as flat-but-fine) value strokes the positive colour; a strictly
// negative value strokes the negative colour. Non-finite deltas fall back to
// the neutral zeroLine so a NaN never renders an alarming red line. Used by
// trend sparklines that colour their stroke by the start->end direction.
export function deltaStroke(theme: ChartTheme, delta: number): string {
  if (!Number.isFinite(delta)) return theme.zeroLine;
  if (delta < 0) return theme.negativeStroke;
  return theme.positiveStroke;
}

// The area-fill companion to deltaStroke, for an <Area> under the trend line.
export function deltaFill(theme: ChartTheme, delta: number): string {
  if (!Number.isFinite(delta)) return "transparent";
  if (delta < 0) return theme.negativeFill;
  return theme.positiveFill;
}
