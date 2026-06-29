// Pure helpers for the /digest daily-counts mini-bar caption (F158 follow-up).
// The per-day bar strip shows volume shape but never names the busiest day or
// the window total, so a glance can't pull out "Tuesday was 31 shots". This
// module summarizes the per_day series into a peak day + total + average, and
// returns the peak bar's index so the page can accent it. DOM-free, testable.

export type DayBucket = { date: string; count: number };

export type DigestPeak = {
  // Index of the busiest day in the input order (first peak on ties), so the
  // page can accent exactly that bar.
  peakIndex: number;
  peakDate: string;
  peakCount: number;
  total: number;
  // Mean shots/day across all buckets, rounded to 1dp.
  avgPerDay: number;
  days: number;
};

// Summarize the per-day series, or null when there's no day to talk about.
// Ignores non-finite counts (treated as 0). First-peak tie-break matches the
// sparkline's peakPointIndex so accents agree across surfaces.
export function digestPeak(days: readonly DayBucket[] | null | undefined): DigestPeak | null {
  if (!Array.isArray(days) || days.length === 0) return null;
  let total = 0;
  let peakIndex = 0;
  let peakCount = -1;
  for (let i = 0; i < days.length; i++) {
    const c = Number.isFinite(days[i]?.count) ? Math.max(0, Math.trunc(days[i].count)) : 0;
    total += c;
    if (c > peakCount) {
      peakCount = c;
      peakIndex = i;
    }
  }
  return {
    peakIndex,
    peakDate: days[peakIndex].date,
    peakCount: Math.max(0, peakCount),
    total,
    avgPerDay: +(total / days.length).toFixed(1),
    days: days.length,
  };
}

// One-line caption beneath the bar strip, e.g. "Busiest May 12 · 31 shots ·
// 8.4/day avg". Quiet "No activity in this window" when the total is zero so
// the caption never trumpets a flat strip. Date is shown raw (yyyy-mm-dd) so
// it matches the bars' own titles.
export function digestPeakCaption(p: DigestPeak | null | undefined): string {
  if (!p || p.total <= 0) return "No activity in this window";
  const noun = p.peakCount === 1 ? "shot" : "shots";
  return `Busiest ${p.peakDate} · ${p.peakCount} ${noun} · ${p.avgPerDay}/day avg`;
}
