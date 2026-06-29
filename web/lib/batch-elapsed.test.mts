// Pure tests for the /batch per-row elapsed helper (F163). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  rowElapsedMs,
  rowElapsedLabel,
  NO_ELAPSED,
  type ElapsedRow,
} from "./batch-elapsed.ts";

test("rowElapsedMs: finish - start, rounded", () => {
  assert.equal(rowElapsedMs({ startedAt: 100, finishedAt: 520.7 }), 421);
});

test("rowElapsedMs: a zero-length interval is a real 0, not null", () => {
  assert.equal(rowElapsedMs({ startedAt: 200, finishedAt: 200 }), 0);
});

test("rowElapsedMs: missing finish (still running) -> null", () => {
  assert.equal(rowElapsedMs({ startedAt: 100 }), null);
});

test("rowElapsedMs: missing start -> null", () => {
  assert.equal(rowElapsedMs({ finishedAt: 100 }), null);
});

test("rowElapsedMs: clock skew (finish before start) -> null", () => {
  assert.equal(rowElapsedMs({ startedAt: 500, finishedAt: 100 }), null);
});

test("rowElapsedMs: non-finite marks -> null", () => {
  assert.equal(rowElapsedMs({ startedAt: NaN, finishedAt: 100 }), null);
  assert.equal(rowElapsedMs({ startedAt: 0, finishedAt: Infinity }), null);
});

test("rowElapsedMs: null / undefined row -> null", () => {
  assert.equal(rowElapsedMs(null), null);
  assert.equal(rowElapsedMs(undefined), null);
});

test("rowElapsedLabel: sub-second uses ms units", () => {
  assert.equal(rowElapsedLabel({ startedAt: 0, finishedAt: 420 }), "420 ms");
});

test("rowElapsedLabel: a second or more uses s units (matches the summary)", () => {
  assert.equal(rowElapsedLabel({ startedAt: 0, finishedAt: 1234 }), "1.23 s");
});

test("rowElapsedLabel: no interval -> em-dash placeholder", () => {
  assert.equal(rowElapsedLabel({ status: "queued" }), NO_ELAPSED);
  assert.equal(rowElapsedLabel(null), NO_ELAPSED);
});

test("rowElapsedLabel: matches the CSV per-row derivation contract", () => {
  // The CSV computes Math.round(finishedAt - startedAt); the label must read
  // off the same number so the column and the export never disagree.
  const row: ElapsedRow = { startedAt: 10.2, finishedAt: 309.9 };
  assert.equal(rowElapsedMs(row), 300);
  assert.equal(rowElapsedLabel(row), "300 ms");
});
