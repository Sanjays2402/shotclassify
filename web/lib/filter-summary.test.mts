// Pure tests for the shots-table filter-summary helpers. Focus on the active-
// filter chip rules and the F91 count-pill label. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  activeFilterChips,
  countActiveFilters,
  filterCountLabel,
  clearFilter,
  clearAllFilters,
  type ShotFilterState,
} from "./filter-summary.ts";

test("activeFilterChips: empty / default state yields no chips", () => {
  for (const f of [
    {},
    { category: "", q: "  ", tag: null, minConfPct: 0, pinnedOnly: false },
    { since: "", until: "" },
  ] as ShotFilterState[]) {
    assert.deepEqual(activeFilterChips(f), [], JSON.stringify(f));
  }
});

test("activeFilterChips: a 0% confidence floor is inert (slider default)", () => {
  assert.equal(countActiveFilters({ minConfPct: 0 }), 0);
  assert.equal(countActiveFilters({ minConfPct: 85 }), 1);
});

test("activeFilterChips: coarse-to-fine reading order", () => {
  const chips = activeFilterChips({
    category: "receipt",
    q: "latte",
    tag: "important",
    minConfPct: 90,
    since: "2026-01-01",
    until: "2026-02-01",
    pinnedOnly: true,
  });
  assert.deepEqual(
    chips.map((c) => c.key),
    ["category", "q", "tag", "minConf", "since", "until", "pinned"],
  );
});

test("filterCountLabel: null at zero, singular at one, plural beyond", () => {
  assert.equal(filterCountLabel({}), null);
  assert.equal(filterCountLabel({ minConfPct: 0 }), null);
  assert.equal(filterCountLabel({ category: "receipt" }), "1 filter");
  assert.equal(
    filterCountLabel({ category: "receipt", pinnedOnly: true }),
    "2 filters",
  );
});

test("filterCountLabel: matches countActiveFilters across a mixed state", () => {
  const f: ShotFilterState = {
    category: "chat",
    q: "ship",
    tag: "",
    minConfPct: 50,
    since: "2026-06-01",
    pinnedOnly: false,
  };
  assert.equal(filterCountLabel(f), `${countActiveFilters(f)} filters`);
  assert.equal(countActiveFilters(f), 4); // category + q + minConf + since
});

test("clearFilter: resets exactly one key to its inert default", () => {
  const f: ShotFilterState = { category: "receipt", pinnedOnly: true };
  const cleared = clearFilter(f, "category");
  assert.equal(cleared.category, "");
  assert.equal(cleared.pinnedOnly, true, "other filters untouched");
});

test("clearAllFilters: every constraint goes inert", () => {
  const f: ShotFilterState = {
    category: "receipt",
    q: "x",
    tag: "y",
    minConfPct: 90,
    since: "2026-01-01",
    until: "2026-02-01",
    pinnedOnly: true,
  };
  assert.equal(countActiveFilters(clearAllFilters(f)), 0);
});
