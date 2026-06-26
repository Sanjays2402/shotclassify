// Pure tests for the /stats chart loading predicate (F37). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { chartsBusy } from "./stats-loading.ts";

test("chartsBusy: pre-mount always shows the skeleton", () => {
  // Before mount recharts can't render regardless of fetch state.
  assert.equal(chartsBusy(false, false, false), true);
  assert.equal(chartsBusy(false, true, false), true);
  assert.equal(chartsBusy(false, false, true), true);
  assert.equal(chartsBusy(false, true, true), true);
});

test("chartsBusy: mounted + loading + no data -> skeleton", () => {
  assert.equal(chartsBusy(true, true, false), true);
});

test("chartsBusy: mounted + loading but data already present -> chart", () => {
  // SWR keepPreviousData / a seeded fallback means we can paint immediately.
  assert.equal(chartsBusy(true, true, true), false);
});

test("chartsBusy: mounted + not loading -> chart, with or without data", () => {
  // No data + not loading is the seeded-sample / error case: render the
  // preview, never an indefinite shimmer.
  assert.equal(chartsBusy(true, false, false), false);
  assert.equal(chartsBusy(true, false, true), false);
});
