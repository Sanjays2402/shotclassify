// Pure Markdown-table summary for the /batch results (F168). The existing
// copy-summary writes a single prose line ("Classified 50 images: 22 receipts,
// 9 chats. Mean conf 78%, 12.3s total."), which is great for a Slack message
// but loses structure when you want a tidy breakdown in a doc / PR / notebook.
// This builds a GitHub-flavoured Markdown table of the class distribution plus
// a metrics footer, so a triager can paste a rendered table instead of a
// run-on sentence. Composes the same lib/batch-classes + lib/batch-stats data
// as the one-liner, so the two can't drift. DOM-free + unit-testable; the
// button owns the clipboard write.

import type { ClassSlice } from "./batch-classes";
import type { BatchStats } from "./batch-stats";
import { ms as fmtMs, pct as fmtPct } from "./categories";

// Escape a cell value for a Markdown table: a literal pipe would break the
// column, so it's backslash-escaped. Labels are app-controlled (no pipes in
// practice) but this keeps the formatter robust.
function cell(v: string): string {
  return v.replace(/\|/g, "\\|");
}

// Build the Markdown table. `doneTotal` is the count of classified images (the
// page passes counts.done). Returns "" when nothing has classified, matching
// batchSummaryText so the button can stay disabled. Unlike the one-liner this
// lists EVERY class (a table doesn't need a "+N more" cap -- rows are cheap and
// scannable), count-desc, with a whole-percent share column. A metrics line
// follows the table as a Markdown blockquote-free caption.
export function batchSummaryMarkdown(
  doneTotal: number,
  dist: readonly ClassSlice[],
  stats: BatchStats,
): string {
  const done = Number.isFinite(doneTotal) ? Math.max(0, Math.trunc(doneTotal)) : 0;
  if (done === 0 || !Array.isArray(dist) || dist.length === 0) return "";

  const header = `Classified ${done} ${done === 1 ? "image" : "images"}`;

  const lines: string[] = [];
  lines.push(`**${header}**`);
  lines.push("");
  lines.push("| Class | Count | Share |");
  lines.push("| --- | ---: | ---: |");
  for (const s of dist) {
    lines.push(`| ${cell(s.label)} | ${s.count} | ${s.sharePct}% |`);
  }

  // Metrics footer -- only the metrics we actually have, mirroring the prose
  // summary's choices (wall time preferred over avg latency).
  const metrics: string[] = [];
  if (stats.meanConfidence !== null) {
    metrics.push(`Mean confidence ${fmtPct(stats.meanConfidence, 0)}`);
  }
  if (stats.wallMs !== null) {
    metrics.push(`Total time ${fmtMs(stats.wallMs)}`);
  } else if (stats.meanLatencyMs !== null) {
    metrics.push(`Mean latency ${fmtMs(stats.meanLatencyMs)}`);
  }
  if (metrics.length) {
    lines.push("");
    lines.push(metrics.join(" \u00b7 "));
  }

  return lines.join("\n");
}
