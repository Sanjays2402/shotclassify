// Pure tests for the /batch progress math (this tick). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  settledCount,
  progressPercent,
  isBatchComplete,
  progressLabel,
  type BatchCounts,
} from "./batch-progress.ts";

const counts = (
  total: number,
  done: number,
  err: number,
  pending: number,
): BatchCounts => ({ total, done, err, pending });

test("settledCount: done + errored rows are both terminal", () => {
  assert.equal(settledCount(counts(10, 6, 2, 2)), 8);
  assert.equal(settledCount(counts(10, 0, 0, 10)), 0);
});

test("progressPercent: ratio rounded to a whole percent", () => {
  assert.equal(progressPercent(counts(50, 12, 0, 38)), 24);
  assert.equal(progressPercent(counts(3, 1, 0, 2)), 33);
  assert.equal(progressPercent(counts(10, 7, 3, 0)), 100);
});

test("progressPercent: empty batch reads 0, not NaN/100", () => {
  assert.equal(progressPercent(counts(0, 0, 0, 0)), 0);
});

test("progressPercent: clamps a transient over-count to 100", () => {
  assert.equal(progressPercent(counts(5, 6, 0, 0)), 100);
});

test("isBatchComplete: every row settled and at least one row", () => {
  assert.equal(isBatchComplete(counts(4, 3, 1, 0)), true);
  assert.equal(isBatchComplete(counts(4, 2, 1, 1)), false);
  assert.equal(isBatchComplete(counts(0, 0, 0, 0)), false);
});

test("progressLabel: mid-run shows N of M processed", () => {
  assert.equal(progressLabel(counts(50, 12, 0, 38)), "12 of 50 processed");
});

test("progressLabel: complete drops the redundant of-M", () => {
  assert.equal(progressLabel(counts(10, 10, 0, 0)), "10 processed");
});

test("progressLabel: names errors, pluralising", () => {
  assert.equal(progressLabel(counts(10, 5, 1, 4)), "6 of 10 processed \u00b7 1 error");
  assert.equal(progressLabel(counts(10, 8, 2, 0)), "10 processed \u00b7 2 errors");
});

test("progressLabel: empty batch yields an empty string", () => {
  assert.equal(progressLabel(counts(0, 0, 0, 0)), "");
});

test("all helpers: non-finite tallies coerce to 0", () => {
  const bad = counts(NaN, NaN, NaN, NaN);
  assert.equal(settledCount(bad), 0);
  assert.equal(progressPercent(bad), 0);
  assert.equal(isBatchComplete(bad), false);
  assert.equal(progressLabel(bad), "");
});
