// Pure tests for the /stats confidence-trend summary (F65). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  hasConfTrend,
  confTrend,
  confTrendDeltaLabel,
  type ConfBucket,
} from "./conf-trend.ts";

const rising: ConfBucket[] = [
  { count: 5, mean_confidence: 0.7 },
  { count: 3, mean_confidence: 0.76 },
  { count: 8, mean_confidence: 0.82 },
];

test("hasConfTrend: needs two populated buckets", () => {
  assert.equal(hasConfTrend(rising), true);
  assert.equal(hasConfTrend([{ count: 5, mean_confidence: 0.8 }]), false);
  assert.equal(hasConfTrend([{ count: 0, mean_confidence: 0.9 }, { count: 0, mean_confidence: 0.9 }]), false);
  assert.equal(hasConfTrend([]), false);
  assert.equal(hasConfTrend(null), false);
});

test("confTrend: first/last/peak whole percent + signed delta", () => {
  const t = confTrend(rising);
  assert.ok(t);
  assert.equal(t.firstPct, 70);
  assert.equal(t.lastPct, 82);
  assert.equal(t.peakPct, 82);
  assert.equal(t.deltaPts, 12);
  assert.equal(t.arrow, "up");
  assert.equal(t.populated, 3);
});

test("confTrend: skips zero-count buckets, falling trend reads down", () => {
  const t = confTrend([
    { count: 0, mean_confidence: 0.99 },
    { count: 4, mean_confidence: 0.8 },
    { count: 2, mean_confidence: 0.74 },
  ]);
  assert.ok(t);
  assert.equal(t.firstPct, 80);
  assert.equal(t.lastPct, 74);
  assert.equal(t.arrow, "down");
  assert.equal(t.populated, 2);
});

test("confTrend: clamps out-of-range and flat reads flat", () => {
  const t = confTrend([
    { count: 1, mean_confidence: 1.5 },
    { count: 1, mean_confidence: 1.5 },
  ]);
  assert.ok(t);
  assert.equal(t.firstPct, 100);
  assert.equal(t.arrow, "flat");
  assert.equal(t.deltaPts, 0);
});

test("confTrend: null for too-few buckets", () => {
  assert.equal(confTrend([{ count: 9, mean_confidence: 0.8 }]), null);
  assert.equal(confTrend([]), null);
});

test("confTrendDeltaLabel: signed pts, bare zero, null", () => {
  assert.equal(confTrendDeltaLabel(confTrend(rising)), "+12.0pts");
  assert.equal(confTrendDeltaLabel(confTrend([{ count: 1, mean_confidence: 0.8 }, { count: 1, mean_confidence: 0.8 }])), "0pts");
  assert.equal(confTrendDeltaLabel(null), null);
});
