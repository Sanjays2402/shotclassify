// Pure tests for the /batch copy-summary formatter (this tick). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { batchSummaryText } from "./batch-summary-text.ts";
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

test("batchSummaryText: head + class list + metrics", () => {
  const dist = [
    slice("receipt", "Receipt", 22, 44),
    slice("chat_screenshot", "Chat screenshot", 9, 18),
  ];
  const s = batchSummaryText(50, dist, stats({ done: 50, meanConfidence: 0.78, wallMs: 12300 }));
  assert.equal(
    s,
    "Classified 50 images: 22 receipts, 9 chat screenshots. Mean conf 78%, 12.30 s total.",
  );
});

test("batchSummaryText: singular image + singular noun", () => {
  const s = batchSummaryText(1, [slice("receipt", "Receipt", 1, 100)], stats({ done: 1 }));
  assert.equal(s, "Classified 1 image: 1 receipt.");
});

test("batchSummaryText: caps the class list and summarises the remainder", () => {
  const dist = [
    slice("receipt", "Receipt", 5, 30),
    slice("code_snippet", "Code snippet", 4, 24),
    slice("chat_screenshot", "Chat screenshot", 3, 18),
    slice("meme", "Meme", 2, 12),
    slice("chart", "Chart", 1, 6),
    slice("other", "Other", 1, 6),
  ];
  const s = batchSummaryText(16, dist, stats({ done: 16 }), 4);
  assert.match(s, /5 receipts, 4 code snippets, 3 chat screenshots, 2 memes, \+2 more\./);
});

test("batchSummaryText: falls back to avg latency when no wall time", () => {
  const s = batchSummaryText(
    3,
    [slice("receipt", "Receipt", 3, 100)],
    stats({ done: 3, meanLatencyMs: 320 }),
  );
  assert.equal(s, "Classified 3 images: 3 receipts. 320 ms avg.");
});

test("batchSummaryText: no metrics clause when stats are bare", () => {
  const s = batchSummaryText(2, [slice("receipt", "Receipt", 2, 100)], stats({ done: 2 }));
  assert.equal(s, "Classified 2 images: 2 receipts.");
});

test("batchSummaryText: empty distribution or zero done -> empty string", () => {
  assert.equal(batchSummaryText(0, [], stats()), "");
  assert.equal(batchSummaryText(5, [], stats({ done: 5 })), "");
  assert.equal(
    batchSummaryText(0, [slice("receipt", "Receipt", 1, 100)], stats()),
    "",
  );
});

test("batchSummaryText: non-finite done coerces to 0 (empty)", () => {
  assert.equal(batchSummaryText(NaN, [slice("receipt", "Receipt", 1, 100)], stats()), "");
});

test("batchSummaryText: conf-only metrics omit the timing clause", () => {
  const s = batchSummaryText(
    4,
    [slice("receipt", "Receipt", 4, 100)],
    stats({ done: 4, meanConfidence: 0.9 }),
  );
  assert.equal(s, "Classified 4 images: 4 receipts. Mean conf 90%.");
});
