// Pure clipboard-summary formatter for the /batch results (this tick). After a
// run, the only way to share what happened was to download the CSV and read
// it. This builds a single human line you can paste into Slack / notes:
//   "Classified 50 images: 22 receipts, 9 chats, 8 code. Mean conf 78%,
//    12.3s total."
// It composes the class distribution (lib/batch-classes) and the timing /
// confidence aggregate (lib/batch-stats) into one string, so the copy can't
// drift from the on-screen chips + summary strip. DOM-free so the wording is
// unit-testable; the button owns the clipboard write.

import type { ClassSlice } from "./batch-classes";
import type { BatchStats } from "./batch-stats";

// Reuse categories' formatters so the copied numbers match the UI exactly.
import { ms as fmtMs, pct as fmtPct } from "./categories";

// Lowercase the human label for the inline list ("22 receipts") and pluralise
// naively by count -- good enough for a paste-able recap, not a grammar engine.
function slicePhrase(s: ClassSlice): string {
  const noun = s.label.toLowerCase();
  // Most labels are single words; "ui mockup" / "error stacktrace" stay as-is
  // and just take a trailing s, which reads fine ("3 ui mockups").
  const plural = s.count === 1 ? noun : `${noun}s`;
  return `${s.count} ${plural}`;
}

// Build the summary line. `doneTotal` is the count of classified images (the
// page passes counts.done). Returns "" when nothing has classified, so the
// button can stay disabled / hidden. The class list is capped to the top
// `maxClasses` so a wide batch doesn't paste a paragraph; a remainder is
// summarised as "+N more".
export function batchSummaryText(
  doneTotal: number,
  dist: readonly ClassSlice[],
  stats: BatchStats,
  maxClasses = 4,
): string {
  const done = Number.isFinite(doneTotal) ? Math.max(0, Math.trunc(doneTotal)) : 0;
  if (done === 0 || !Array.isArray(dist) || dist.length === 0) return "";

  const head = `Classified ${done} ${done === 1 ? "image" : "images"}`;

  const shown = dist.slice(0, Math.max(1, maxClasses));
  const rest = dist.length - shown.length;
  const parts = shown.map(slicePhrase);
  if (rest > 0) parts.push(`+${rest} more`);
  const classList = parts.join(", ");

  // Trailing metrics clause -- only the metrics we actually have.
  const metrics: string[] = [];
  if (stats.meanConfidence !== null) {
    metrics.push(`mean conf ${fmtPct(stats.meanConfidence, 0)}`);
  }
  if (stats.wallMs !== null) {
    metrics.push(`${fmtMs(stats.wallMs)} total`);
  } else if (stats.meanLatencyMs !== null) {
    metrics.push(`${fmtMs(stats.meanLatencyMs)} avg`);
  }

  const tail = metrics.length ? ` ${capitalize(metrics.join(", "))}.` : "";
  return `${head}: ${classList}.${tail}`;
}

function capitalize(s: string): string {
  return s.length ? s[0].toUpperCase() + s.slice(1) : s;
}
