// Pure tests for the shots view-mode helpers. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseViewMode,
  nextViewMode,
  labelForViewMode,
  isTabular,
  isCompact,
  SHOTS_VIEW_STORAGE_KEY,
  SHOTS_VIEW_MODES,
} from "./view-mode.ts";

test("SHOTS_VIEW_STORAGE_KEY is stable", () => {
  // Hard-coded so a rename is reviewed deliberately (a change orphans every
  // user's saved preference).
  assert.equal(SHOTS_VIEW_STORAGE_KEY, "shotclassify.shots.view");
});

test("SHOTS_VIEW_MODES lists exactly the three known modes", () => {
  assert.deepEqual(SHOTS_VIEW_MODES, ["table", "grid", "compact"]);
});

test("parseViewMode: accepts every known mode, case-insensitive + trimmed", () => {
  assert.equal(parseViewMode("table"), "table");
  assert.equal(parseViewMode("GRID"), "grid");
  assert.equal(parseViewMode("  Compact  "), "compact");
});

test("parseViewMode: falls back to table on anything unrecognised", () => {
  assert.equal(parseViewMode(null), "table");
  assert.equal(parseViewMode(undefined), "table");
  assert.equal(parseViewMode(""), "table");
  assert.equal(parseViewMode("gallery"), "table");
});

test("nextViewMode: cycles table -> grid -> compact -> table", () => {
  assert.equal(nextViewMode("table"), "grid");
  assert.equal(nextViewMode("grid"), "compact");
  assert.equal(nextViewMode("compact"), "table");
});

test("labelForViewMode: user-facing label per mode", () => {
  assert.equal(labelForViewMode("table"), "Table");
  assert.equal(labelForViewMode("grid"), "Grid");
  assert.equal(labelForViewMode("compact"), "Compact");
});

test("isTabular: table and compact render the table, grid does not", () => {
  assert.equal(isTabular("table"), true);
  assert.equal(isTabular("compact"), true);
  assert.equal(isTabular("grid"), false);
});

test("isCompact: only compact uses the tight chrome", () => {
  assert.equal(isCompact("compact"), true);
  assert.equal(isCompact("table"), false);
  assert.equal(isCompact("grid"), false);
});
