// Pure tests for the `o`-key preview-target resolution (F118). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { firstVisibleId, pickPreviewTarget } from "./preview-key.ts";

test("firstVisibleId: returns the first non-blank id", () => {
  assert.equal(firstVisibleId(["a", "b", "c"]), "a");
  // @ts-expect-error -- exercising malformed leading entries at runtime
  assert.equal(firstVisibleId(["", null, "real"]), "real");
});

test("firstVisibleId: null on an empty / non-array list", () => {
  assert.equal(firstVisibleId([]), null);
  // @ts-expect-error -- exercising a non-array at runtime
  assert.equal(firstVisibleId(null), null);
});

test("pickPreviewTarget: honours a focused id that's in the visible list", () => {
  assert.equal(pickPreviewTarget("b", ["a", "b", "c"]), "b");
});

test("pickPreviewTarget: falls back to the first row when focus isn't on a row", () => {
  assert.equal(pickPreviewTarget(null, ["a", "b"]), "a");
  assert.equal(pickPreviewTarget(undefined, ["a", "b"]), "a");
});

test("pickPreviewTarget: ignores a stale focused id not in the visible list", () => {
  // The focused row paged away -> don't target something off-screen.
  assert.equal(pickPreviewTarget("gone", ["a", "b"]), "a");
});

test("pickPreviewTarget: null when there are no visible rows", () => {
  assert.equal(pickPreviewTarget("b", []), null);
  assert.equal(pickPreviewTarget(null, []), null);
});
