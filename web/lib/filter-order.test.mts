// Pure tests for the /shots filter-toolbar Tab order (F138). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  SHOTS_FILTER_ORDER,
  SHOTS_FILTER_TABINDEX_BASE,
  filterTabIndex,
  nextFilterControl,
  prevFilterControl,
} from "./filter-order.ts";

test("order leads with class then search, ends with pinned", () => {
  assert.equal(SHOTS_FILTER_ORDER[0], "class");
  assert.equal(SHOTS_FILTER_ORDER[1], "search");
  assert.equal(SHOTS_FILTER_ORDER[SHOTS_FILTER_ORDER.length - 1], "pinned");
});

test("order has no duplicates", () => {
  assert.equal(new Set(SHOTS_FILTER_ORDER).size, SHOTS_FILTER_ORDER.length);
});

test("filterTabIndex is a strictly increasing 1-based roving sequence", () => {
  const idxs = SHOTS_FILTER_ORDER.map(filterTabIndex);
  for (let i = 1; i < idxs.length; i++) {
    assert.ok(idxs[i] > idxs[i - 1], `index ${i} ascends`);
  }
  assert.equal(idxs[0], SHOTS_FILTER_TABINDEX_BASE + 1);
});

test("filterTabIndex puts class before search", () => {
  assert.ok(filterTabIndex("class") < filterTabIndex("search"));
  assert.ok(filterTabIndex("search") < filterTabIndex("pinned"));
});

test("filterTabIndex of an unknown control falls back to 0 (natural order)", () => {
  assert.equal(filterTabIndex("mystery"), 0);
});

test("nextFilterControl walks forward and wraps", () => {
  assert.equal(nextFilterControl("class"), "search");
  assert.equal(nextFilterControl("pinned"), "class");
});

test("prevFilterControl walks back and wraps", () => {
  assert.equal(prevFilterControl("search"), "class");
  assert.equal(prevFilterControl("class"), "pinned");
});

test("next/prev unknown lands on a valid end", () => {
  assert.equal(nextFilterControl("nope" as never), "class");
  assert.equal(prevFilterControl("nope" as never), "pinned");
});

test("next then prev is identity for every control", () => {
  for (const c of SHOTS_FILTER_ORDER) {
    assert.equal(prevFilterControl(nextFilterControl(c)), c);
  }
});
