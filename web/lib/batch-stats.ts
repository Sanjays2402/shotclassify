// Pure results-summary math for the /batch page (this tick). Each row records
// startedAt / finishedAt (perf timestamps) and a confidence, and the CSV
// export already derives a per-row elapsed -- but the UI never surfaced the
// AGGREGATE: how long the whole run took, the mean per-image latency, and the
// mean classifier confidence across the batch. This module rolls the done rows
// into those three readouts so the page can show a compact summary strip.
// DOM-free so the arithmetic is unit-testable; the component formats + renders.

// Minimal row shape the summary reads. The page Row is a superset; only `done`
// rows carry the timing + confidence we average over.
export type TimedRow = {
  status: string;
  startedAt?: number;
  finishedAt?: number;
  confidence?: number;
};

export type BatchStats = {
  // Number of done rows that contributed to the averages.
  done: number;
  // Mean per-image latency in ms (start->finish), rounded; null when no row
  // has a usable interval.
  meanLatencyMs: number | null;
  // Mean classifier confidence as a 0..1 fraction, or null when no done row
  // carried a confidence.
  meanConfidence: number | null;
  // Total wall-clock span of the run (earliest start -> latest finish) in ms,
  // or null when nothing has timing. This is REAL elapsed time, so overlapping
  // concurrent work isn't double-counted (unlike summing per-row latencies).
  wallMs: number | null;
};

function isFiniteNum(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

// Build the aggregate. Skips non-done rows entirely; within done rows, a row
// contributes to a given average only if it has the relevant finite field, so
// a row missing timing still counts toward mean confidence and vice versa.
export function batchStats(rows: readonly TimedRow[] | null | undefined): BatchStats {
  const empty: BatchStats = {
    done: 0,
    meanLatencyMs: null,
    meanConfidence: null,
    wallMs: null,
  };
  if (!Array.isArray(rows)) return empty;

  let done = 0;
  let latSum = 0;
  let latN = 0;
  let confSum = 0;
  let confN = 0;
  let minStart = Infinity;
  let maxFinish = -Infinity;

  for (const r of rows) {
    if (!r || r.status !== "done") continue;
    done += 1;
    if (isFiniteNum(r.startedAt) && isFiniteNum(r.finishedAt) && r.finishedAt >= r.startedAt) {
      latSum += r.finishedAt - r.startedAt;
      latN += 1;
      if (r.startedAt < minStart) minStart = r.startedAt;
      if (r.finishedAt > maxFinish) maxFinish = r.finishedAt;
    }
    if (isFiniteNum(r.confidence)) {
      confSum += Math.min(1, Math.max(0, r.confidence));
      confN += 1;
    }
  }

  if (done === 0) return empty;
  return {
    done,
    meanLatencyMs: latN > 0 ? Math.round(latSum / latN) : null,
    meanConfidence: confN > 0 ? confSum / confN : null,
    wallMs: latN > 0 ? Math.round(maxFinish - minStart) : null,
  };
}

// True when there's at least one done row with timing OR confidence to show --
// lets the page hide the whole strip until a run has produced real numbers.
export function hasBatchStats(s: BatchStats): boolean {
  return s.done > 0 && (s.meanLatencyMs !== null || s.meanConfidence !== null);
}
