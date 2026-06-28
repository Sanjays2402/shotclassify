// Pure tests for the /shots "expand / collapse all previews" set-math (F119).
// No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  expandedOnPageCount,
  allPreviewsExpanded,
  anyPreviewsExpanded,
  expandAllPreviews,
  collapseAllPreviews,
  previewToggleAllLabel,
} from "./preview-expand.ts";

test("expandedOnPageCount: counts only ids present in both sets", () => {
  const expanded = new Set(["a", "c", "z"]);
  assert.equal(expandedOnPageCount(expanded, ["a", "b", "c", "d"]), 2);
  assert.equal(expandedOnPageCount(new Set(), ["a", "b"]), 0);
});

test("expandedOnPageCount: cleans malformed / duplicate ids", () => {
  const expanded = new Set(["a"]);
  // @ts-expect-error -- exercising non-string entries at runtime
  assert.equal(expandedOnPageCount(expanded, ["a", "a", "", null, undefined]), 1);
});

test("allPreviewsExpanded: true only when every visible id is open", () => {
  assert.equal(allPreviewsExpanded(new Set(["a", "b"]), ["a", "b"]), true);
  assert.equal(allPreviewsExpanded(new Set(["a"]), ["a", "b"]), false);
});

test("allPreviewsExpanded: false for an empty visible list", () => {
  assert.equal(allPreviewsExpanded(new Set(["a"]), []), false);
});

test("anyPreviewsExpanded: true when at least one visible id is open", () => {
  assert.equal(anyPreviewsExpanded(new Set(["x", "a"]), ["a", "b"]), true);
  assert.equal(anyPreviewsExpanded(new Set(["x"]), ["a", "b"]), false);
  assert.equal(anyPreviewsExpanded(new Set(), ["a"]), false);
});

test("expandAllPreviews: adds every visible id, preserves off-page ids", () => {
  const before = new Set(["offpage"]);
  const after = expandAllPreviews(before, ["a", "b"]);
  assert.deepEqual(Array.from(after).sort(), ["a", "b", "offpage"]);
  // Immutable: original untouched.
  assert.deepEqual(Array.from(before), ["offpage"]);
});

test("collapseAllPreviews: removes only visible ids, preserves off-page ids", () => {
  const before = new Set(["a", "b", "offpage"]);
  const after = collapseAllPreviews(before, ["a", "b"]);
  assert.deepEqual(Array.from(after), ["offpage"]);
  // Immutable: original untouched.
  assert.equal(before.size, 3);
});

test("collapseAllPreviews: a no-op visible list returns an equivalent set", () => {
  const before = new Set(["a"]);
  assert.deepEqual(Array.from(collapseAllPreviews(before, [])), ["a"]);
});

test("previewToggleAllLabel: offers Collapse when all open, else Expand", () => {
  assert.equal(
    previewToggleAllLabel(new Set(["a", "b"]), ["a", "b"]),
    "Collapse all previews",
  );
  assert.equal(
    previewToggleAllLabel(new Set(["a"]), ["a", "b"]),
    "Expand all previews",
  );
  assert.equal(
    previewToggleAllLabel(new Set(), ["a", "b"]),
    "Expand all previews",
  );
});

test("previewToggleAllLabel: null when there are no visible rows", () => {
  assert.equal(previewToggleAllLabel(new Set(["a"]), []), null);
});
