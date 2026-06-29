// Pure tests for the /batch Markdown-table summary (F168). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { batchSummaryMarkdown } from "./batch-summary-markdown.ts";
import type { ClassSlice } from "./batch-classes.ts";
import type { BatchStats } from "./batch-stats.ts";

const slice = (
  category: ClassSlice["category"],
  label: string,
  count: number,
  sharePct: number,
): ClassSlice => ({ category, label, count, sharePct });

const stats = (over: Partial<BatchStats> = {}): BatchStats => ({
  done: 0,
  meanLatencyMs: null,
  meanConfidence: null,
  wallMs: null,
  ...over,
});

test("batchSummaryMarkdown: header, table, and metrics footer", () => {
  const dist = [
    slice("receipt", "Receipt", 22, 44),
    slice("chat_screenshot", "Chat screenshot", 9, 18),
  ];
  const md = batchSummaryMarkdown(
    50,
    dist,
    stats({ done: 50, meanConfidence: 0.78, wallMs: 12300 }),
  );
  assert.equal(
    md,
    [
      "**Classified 50 images**",
      "",
      "| Class | Count | Share |",
      "| --- | ---: | ---: |",
      "| Receipt | 22 | 44% |",
      "| Chat screenshot | 9 | 18% |",
      "",
      "Mean confidence 78% \u00b7 Total time 12.30 s",
    ].join("\n"),
  );
});

test("batchSummaryMarkdown: lists EVERY class, no +N more cap", () => {
  const dist = [
    slice("receipt", "Receipt", 5, 30),
    slice("code_snippet", "Code snippet", 4, 24),
    slice("chat_screenshot", "Chat screenshot", 3, 18),
    slice("meme", "Meme", 2, 12),
    slice("chart", "Chart", 1, 6),
    slice("other", "Other", 1, 6),
  ];
  const md = batchSummaryMarkdown(16, dist, stats({ done: 16 }));
  // All six rows present -- a table doesn't truncate like the prose line.
  assert.ok(md.includes("| Other | 1 | 6% |"));
  assert.equal((md.match(/\| \d+ \| \d+% \|/g) || []).length, 6);
  // No metrics footer when stats are bare.
  assert.ok(!md.includes("Mean"));
  assert.ok(!md.includes("Total time"));
});

test("batchSummaryMarkdown: singular image header", () => {
  const md = batchSummaryMarkdown(
    1,
    [slice("receipt", "Receipt", 1, 100)],
    stats({ done: 1 }),
  );
  assert.ok(md.startsWith("**Classified 1 image**"));
});

test("batchSummaryMarkdown: falls back to mean latency when no wall time", () => {
  const md = batchSummaryMarkdown(
    3,
    [slice("receipt", "Receipt", 3, 100)],
    stats({ done: 3, meanLatencyMs: 320 }),
  );
  assert.ok(md.endsWith("Mean latency 320 ms"));
});

test("batchSummaryMarkdown: conf-only footer omits timing", () => {
  const md = batchSummaryMarkdown(
    4,
    [slice("receipt", "Receipt", 4, 100)],
    stats({ done: 4, meanConfidence: 0.9 }),
  );
  assert.ok(md.endsWith("Mean confidence 90%"));
  assert.ok(!md.includes("\u00b7"));
});

test("batchSummaryMarkdown: empty distribution or zero done -> empty string", () => {
  assert.equal(batchSummaryMarkdown(0, [], stats()), "");
  assert.equal(batchSummaryMarkdown(5, [], stats({ done: 5 })), "");
  assert.equal(
    batchSummaryMarkdown(0, [slice("receipt", "Receipt", 1, 100)], stats()),
    "",
  );
});

test("batchSummaryMarkdown: non-finite done coerces to empty", () => {
  assert.equal(
    batchSummaryMarkdown(NaN, [slice("receipt", "Receipt", 1, 100)], stats()),
    "",
  );
});

test("batchSummaryMarkdown: a pipe in a label is escaped, not column-breaking", () => {
  const md = batchSummaryMarkdown(
    2,
    [slice("other", "Weird|Label", 2, 100)],
    stats({ done: 2 }),
  );
  assert.ok(md.includes("| Weird\\|Label | 2 | 100% |"));
});

test("batchSummaryMarkdown: header row + separator row are well-formed GFM", () => {
  const md = batchSummaryMarkdown(
    1,
    [slice("receipt", "Receipt", 1, 100)],
    stats({ done: 1 }),
  );
  const lines = md.split("\n");
  assert.equal(lines[2], "| Class | Count | Share |");
  assert.equal(lines[3], "| --- | ---: | ---: |");
});
