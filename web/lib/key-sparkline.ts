// Pure series-bucketing + geometry for the /keys/[id] usage sparkline (F140).
// The detail page draws a per-day request sparkline, but the math lived inline
// in the component: peak detection, point projection, the area path, blank-day
// dots. That made the empty / single-point / all-zero edges untestable. This
// DOM-free module owns the geometry so the SVG is a thin render of a tested
// view-model, and any other surface can reuse the same shape.

export type SparkPoint = { day: string; count: number };

export type SparkGeometry = {
  // One projected point per series sample, in input order.
  points: { x: number; y: number; day: string; count: number }[];
  // The "M..L.." line path through all points (empty string when no points).
  linePath: string;
  // The closed path that fills the area under the line (empty when no points).
  areaPath: string;
  // The peak count used to scale the Y axis (>=1 so a flat-zero series is flat).
  peak: number;
  // First / last day labels (raw ISO day) for the axis ends; "" when empty.
  firstDay: string;
  lastDay: string;
};

export type SparkOpts = {
  width?: number;
  height?: number;
  padX?: number;
  padY?: number;
};

const DEFAULTS = { width: 720, height: 96, padX: 8, padY: 12 } as const;

// Clean an arbitrary series into well-formed {day,count} samples: drop non-
// objects, coerce a non-finite / negative count to 0, stringify the day. Keeps
// input order. A non-array yields []. Used by both geometry + summary so they
// can never disagree on what counts as a valid point.
export function cleanSeries(series: readonly SparkPoint[] | null | undefined): SparkPoint[] {
  if (!Array.isArray(series)) return [];
  const out: SparkPoint[] = [];
  for (const s of series) {
    if (!s || typeof s !== "object") continue;
    const day = typeof s.day === "string" ? s.day : "";
    const n = Number(s.count);
    out.push({ day, count: Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0 });
  }
  return out;
}

// Project a daily series into SVG geometry. The peak is floored at 1 so an
// all-zero window draws a flat baseline rather than dividing by zero; a single
// point sits at the left edge. Mirrors the historical inline component exactly
// so the visual is unchanged, only now testable.
export function sparklineGeometry(
  series: readonly SparkPoint[] | null | undefined,
  opts: SparkOpts = {},
): SparkGeometry {
  const { width, height, padX, padY } = { ...DEFAULTS, ...opts };
  const pts = cleanSeries(series);
  const peak = Math.max(1, ...pts.map((p) => p.count));
  const stepX = pts.length > 1 ? (width - padX * 2) / (pts.length - 1) : 0;
  const points = pts.map((s, i) => ({
    x: padX + i * stepX,
    y: padY + (height - padY * 2) * (1 - s.count / peak),
    day: s.day,
    count: s.count,
  }));
  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(" ");
  const areaPath = points.length
    ? `${linePath} L ${(padX + (pts.length - 1) * stepX).toFixed(1)} ${height - padY} L ${padX.toFixed(1)} ${height - padY} Z`
    : "";
  return {
    points,
    linePath,
    areaPath,
    peak,
    firstDay: pts[0]?.day ?? "",
    lastDay: pts[pts.length - 1]?.day ?? "",
  };
}

export type SparkSummary = {
  total: number;
  peak: number;
  // The day with the most requests, or "" when the series is empty / all-zero.
  busiestDay: string;
  // True when there's at least one day with a non-zero count.
  hasTraffic: boolean;
};

// Roll a series into glanceable facts for the sparkline caption. busiestDay
// ties resolve to the FIRST peak (left-most) so the label is deterministic. An
// all-zero / empty series reports hasTraffic=false and an empty busiestDay.
export function summarizeSeries(
  series: readonly SparkPoint[] | null | undefined,
): SparkSummary {
  const pts = cleanSeries(series);
  let total = 0;
  let peak = 0;
  let busiestDay = "";
  for (const p of pts) {
    total += p.count;
    if (p.count > peak) {
      peak = p.count;
      busiestDay = p.day;
    }
  }
  return { total, peak, busiestDay, hasTraffic: peak > 0 };
}
