// Pure tests for the shots filter-breadcrumb helpers. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  activeFilterChips,
  countActiveFilters,
  clearFilter,
  clearAllFilters,
  type ShotFilterState,
} from "./filter-summary.ts";

test("activeFilterChips: empty state yields no chips", () => {
  assert.deepEqual(activeFilterChips({}), []);
  assert.equal(countActiveFilters({}), 0);
});

test("activeFilterChips: category resolves to its long label", () => {
  const chips = activeFilterChips({ category: "receipt" });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].key, "category");
  assert.equal(chips[0].field, "Class");
  assert.equal(chips[0].value, "Receipt");
  assert.equal(chips[0].label, "Class: Receipt");
});

test("activeFilterChips: unknown category falls back to the raw value", () => {
  const chips = activeFilterChips({ category: "weird_cat" });
  assert.equal(chips[0].value, "weird_cat");
});

test("activeFilterChips: search is quoted and long queries truncate", () => {
  const short = activeFilterChips({ q: "uber eats" });
  assert.equal(short[0].key, "q");
  assert.equal(short[0].value, '"uber eats"');

  const long = activeFilterChips({
    q: "a really long search string that should be cut off somewhere",
  });
  assert.match(long[0].value, /…"$/);
  // The ellipsis-trimmed value should be shorter than the original.
  assert.ok(long[0].value.length < 64);
});

test("activeFilterChips: tag prefixes with #", () => {
  const chips = activeFilterChips({ tag: "reimburse" });
  assert.equal(chips[0].key, "tag");
  assert.equal(chips[0].value, "#reimburse");
});

test("activeFilterChips: a 0% confidence floor is NOT a constraint", () => {
  assert.equal(activeFilterChips({ minConfPct: 0 }).length, 0);
});

test("activeFilterChips: a positive confidence floor renders as >= percent", () => {
  const chips = activeFilterChips({ minConfPct: 85 });
  assert.equal(chips[0].key, "minConf");
  assert.equal(chips[0].value, "≥85%");
});

test("activeFilterChips: since / until each get their own chip", () => {
  const chips = activeFilterChips({ since: "2026-01-01", until: "2026-02-01" });
  const keys = chips.map((c) => c.key);
  assert.deepEqual(keys, ["since", "until"]);
  assert.equal(chips[0].label, "From: 2026-01-01");
  assert.equal(chips[1].label, "Until: 2026-02-01");
});

test("activeFilterChips: pinnedOnly yields a boolean chip", () => {
  const chips = activeFilterChips({ pinnedOnly: true });
  assert.equal(chips[0].key, "pinned");
  assert.equal(chips[0].label, "Pinned only");
  // false / undefined produce nothing.
  assert.equal(activeFilterChips({ pinnedOnly: false }).length, 0);
});

test("activeFilterChips: ordering is class, search, tag, conf, dates, pinned", () => {
  const full: ShotFilterState = {
    pinnedOnly: true,
    until: "2026-03-01",
    since: "2026-01-01",
    minConfPct: 70,
    tag: "x",
    q: "coffee",
    category: "code_snippet",
  };
  const keys = activeFilterChips(full).map((c) => c.key);
  assert.deepEqual(keys, [
    "category",
    "q",
    "tag",
    "minConf",
    "since",
    "until",
    "pinned",
  ]);
  assert.equal(countActiveFilters(full), 7);
});

test("clearFilter: resets only the named filter to its inert default", () => {
  const f: ShotFilterState = {
    category: "receipt",
    q: "coffee",
    minConfPct: 80,
    pinnedOnly: true,
  };
  const noCat = clearFilter(f, "category");
  assert.equal(noCat.category, "");
  assert.equal(noCat.q, "coffee"); // untouched
  assert.equal(clearFilter(f, "minConf").minConfPct, 0);
  assert.equal(clearFilter(f, "pinned").pinnedOnly, false);
  // Original is not mutated.
  assert.equal(f.category, "receipt");
});

test("clearAllFilters: wipes every constraint at once", () => {
  const f: ShotFilterState = {
    category: "receipt",
    q: "coffee",
    tag: "x",
    minConfPct: 90,
    since: "2026-01-01",
    until: "2026-02-01",
    pinnedOnly: true,
  };
  const cleared = clearAllFilters(f);
  assert.equal(countActiveFilters(cleared), 0);
  assert.equal(cleared.category, "");
  assert.equal(cleared.minConfPct, 0);
  assert.equal(cleared.pinnedOnly, false);
});
