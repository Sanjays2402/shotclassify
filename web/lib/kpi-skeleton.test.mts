// Pure tests for the KPI-card skeleton helpers (F146). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  KPI_CARD_COUNT,
  kpiSkeletonKeys,
  showKpiSkeleton,
} from "./kpi-skeleton.ts";

test("KPI_CARD_COUNT matches the four box-score cards", () => {
  assert.equal(KPI_CARD_COUNT, 4);
});

test("kpiSkeletonKeys: default count yields four unique stable keys", () => {
  const keys = kpiSkeletonKeys();
  assert.equal(keys.length, 4);
  assert.equal(new Set(keys).size, 4);
  assert.deepEqual(keys, [
    "kpi-skeleton-0",
    "kpi-skeleton-1",
    "kpi-skeleton-2",
    "kpi-skeleton-3",
  ]);
});

test("kpiSkeletonKeys: respects an explicit count, guards bad input", () => {
  assert.equal(kpiSkeletonKeys(2).length, 2);
  assert.equal(kpiSkeletonKeys(0).length, 0);
  assert.equal(kpiSkeletonKeys(-3).length, 0);
  assert.equal(kpiSkeletonKeys(NaN).length, 0);
  assert.equal(kpiSkeletonKeys(3.9).length, 3);
});

test("showKpiSkeleton: only true while busy", () => {
  assert.equal(showKpiSkeleton(true), true);
  assert.equal(showKpiSkeleton(false), false);
});
