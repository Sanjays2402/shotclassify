// Pure tests for the /keys calls mini-bar (F152). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { callCount, fleetMaxCalls, callBar, callBarTitle, fleetTotalCalls, fleetShareLabel } from "./key-callbar.ts";

test("callCount: clean integer, non-finite / negative / fractional guarded", () => {
  assert.equal(callCount({ usage_count: 12 }), 12);
  assert.equal(callCount({ usage_count: 0 }), 0);
  assert.equal(callCount({ usage_count: -5 }), 0);
  assert.equal(callCount({ usage_count: 2.9 }), 2);
  assert.equal(callCount({ usage_count: null }), 0);
  assert.equal(callCount(undefined), 0);
});

test("fleetMaxCalls: peak across rows, floored at 1, non-array safe", () => {
  assert.equal(fleetMaxCalls([{ usage_count: 4 }, { usage_count: 120 }, { usage_count: 9 }]), 120);
  assert.equal(fleetMaxCalls([{ usage_count: 0 }, { usage_count: 0 }]), 1);
  assert.equal(fleetMaxCalls([]), 1);
  assert.equal(fleetMaxCalls(null), 1);
});

test("callBar: ratio + width scale to the fleet max", () => {
  const b = callBar(50, 100);
  assert.equal(b.ratio, 0.5);
  assert.equal(b.widthPct, "50%");
  assert.equal(b.isBusiest, false);
});

test("callBar: busiest key fills and is flagged", () => {
  const b = callBar(100, 100);
  assert.equal(b.widthPct, "100%");
  assert.equal(b.isBusiest, true);
});

test("callBar: a tiny non-zero count still shows a 2% minimum sliver", () => {
  const b = callBar(1, 10000);
  assert.equal(b.widthPct, "2%");
  assert.equal(b.isBusiest, false);
});

test("callBar: zero calls reads empty + not busiest", () => {
  const b = callBar(0, 100);
  assert.equal(b.widthPct, "0%");
  assert.equal(b.isBusiest, false);
});

test("callBarTitle: humanised hover, never-called branch", () => {
  assert.equal(callBarTitle(1204, 3200), "1,204 calls (38% of fleet peak)");
  assert.equal(callBarTitle(1, 4), "1 call (25% of fleet peak)");
  assert.equal(callBarTitle(0, 100), "Never called");
});

test("fleetTotalCalls: sums coerced counts, floors at 1", () => {
  assert.equal(fleetTotalCalls([{ usage_count: 10 }, { usage_count: 30 }]), 40);
  assert.equal(fleetTotalCalls([{ usage_count: -5 }, { usage_count: 0 }]), 1);
  assert.equal(fleetTotalCalls([]), 1);
  assert.equal(fleetTotalCalls(null), 1);
});

test("fleetShareLabel: share of total, <1% floor, null at zero", () => {
  assert.equal(fleetShareLabel(320, 1000), "32% of fleet traffic");
  assert.equal(fleetShareLabel(2, 1000), "<1% of fleet traffic");
  assert.equal(fleetShareLabel(0, 1000), null);
  assert.equal(fleetShareLabel(50, 100), "50% of fleet traffic");
});
