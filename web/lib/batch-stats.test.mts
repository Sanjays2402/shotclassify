// Pure tests for the /batch results-summary math (this tick). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { batchStats, hasBatchStats, type TimedRow } from "./batch-stats.ts";

test("batchStats: means over done rows with finite fields", () => {
  const rows: TimedRow[] = [
    { status: "done", startedAt: 0, finishedAt: 200, confidence: 0.8 },
    { status: "done", startedAt: 100, finishedAt: 500, confidence: 0.6 },
  ];
  const s = batchStats(rows);
  assert.equal(s.done, 2);
  assert.equal(s.meanLatencyMs, 300); // (200 + 400) / 2
  assert.equal(s.meanConfidence, 0.7);
});

test("batchStats: wall span is earliest-start to latest-finish, not the sum", () => {
  // Two overlapping concurrent items: per-row latencies sum to 600, but real
  // wall time is only 500 (0 -> 500).
  const s = batchStats([
    { status: "done", startedAt: 0, finishedAt: 300 },
    { status: "done", startedAt: 200, finishedAt: 500 },
  ]);
  assert.equal(s.wallMs, 500);
  assert.equal(s.meanLatencyMs, 300);
});

test("batchStats: skips non-done rows", () => {
  const s = batchStats([
    { status: "done", startedAt: 0, finishedAt: 100, confidence: 0.9 },
    { status: "running", startedAt: 0, finishedAt: 100, confidence: 0.1 },
    { status: "error", confidence: 0.2 },
    { status: "queued" },
  ]);
  assert.equal(s.done, 1);
  assert.equal(s.meanConfidence, 0.9);
  assert.equal(s.meanLatencyMs, 100);
});

test("batchStats: a row missing timing still counts toward confidence", () => {
  const s = batchStats([
    { status: "done", confidence: 0.5 },
    { status: "done", startedAt: 0, finishedAt: 100, confidence: 0.7 },
  ]);
  assert.equal(s.done, 2);
  assert.equal(s.meanConfidence, 0.6);
  // Only the second row had timing.
  assert.equal(s.meanLatencyMs, 100);
  assert.equal(s.wallMs, 100);
});

test("batchStats: confidence clamps to 0..1 before averaging", () => {
  const s = batchStats([
    { status: "done", confidence: 1.4 },
    { status: "done", confidence: 0.6 },
  ]);
  // 1.4 clamps to 1.0 -> mean (1 + 0.6)/2 = 0.8
  assert.equal(s.meanConfidence, 0.8);
});

test("batchStats: a negative interval (clock skew) is ignored", () => {
  const s = batchStats([
    { status: "done", startedAt: 500, finishedAt: 100, confidence: 0.5 },
  ]);
  assert.equal(s.meanLatencyMs, null);
  assert.equal(s.wallMs, null);
  // Confidence still counts.
  assert.equal(s.meanConfidence, 0.5);
});

test("batchStats: empty / non-array / no-done -> all-null shell", () => {
  for (const input of [[], null, undefined, [{ status: "queued" } as TimedRow]]) {
    const s = batchStats(input as TimedRow[]);
    assert.equal(s.done, 0);
    assert.equal(s.meanLatencyMs, null);
    assert.equal(s.meanConfidence, null);
    assert.equal(s.wallMs, null);
  }
});

test("hasBatchStats: true only with a done row carrying real numbers", () => {
  assert.equal(hasBatchStats(batchStats([{ status: "done", confidence: 0.5 }])), true);
  assert.equal(
    hasBatchStats(batchStats([{ status: "done", startedAt: 0, finishedAt: 50 }])),
    true,
  );
  assert.equal(hasBatchStats(batchStats([])), false);
  // A done row with no timing AND no confidence has nothing to show.
  assert.equal(hasBatchStats(batchStats([{ status: "done" }])), false);
});
