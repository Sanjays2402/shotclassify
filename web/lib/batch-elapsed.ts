// Pure per-row elapsed helper for the /batch table (F163). Every row records a
// startedAt / finishedAt perf timestamp, and the CSV export already derives a
// per-image elapsed from them -- but the on-screen table never showed it, so
// you had to download the export to see which frame was slow. This module turns
// a single row's timestamps into a finished-interval (ms) plus a formatted
// label, so the table can carry an "Elapsed" column that agrees with the CSV.
// DOM-free so the arithmetic + formatting is unit-testable.

import { ms as fmtMs } from "./categories";

// Minimal row shape: only the two perf marks + status matter here. The page
// Row is a superset.
export type ElapsedRow = {
  status?: string;
  startedAt?: number;
  finishedAt?: number;
};

function isFiniteNum(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

// The elapsed interval in ms for a row, or null when it can't be measured.
// A row needs BOTH a finite start and a finite finish with finish >= start;
// a queued/running row (no finish yet) or a clock-skewed pair yields null so
// the cell shows a placeholder rather than a bogus or negative duration.
export function rowElapsedMs(row: ElapsedRow | null | undefined): number | null {
  if (!row) return null;
  if (!isFiniteNum(row.startedAt) || !isFiniteNum(row.finishedAt)) return null;
  if (row.finishedAt < row.startedAt) return null;
  return Math.round(row.finishedAt - row.startedAt);
}

// The placeholder for a cell with no measurable interval -- one em dash,
// matching the rest of the batch table's empty cells.
export const NO_ELAPSED = "\u2014";

// Formatted elapsed label for the table cell, reusing categories' `ms` so the
// units ("420 ms" / "1.20 s") match the aggregate summary strip and the rest
// of the app. Returns the em-dash placeholder when there's no interval.
export function rowElapsedLabel(row: ElapsedRow | null | undefined): string {
  const elapsed = rowElapsedMs(row);
  return elapsed === null ? NO_ELAPSED : fmtMs(elapsed);
}
