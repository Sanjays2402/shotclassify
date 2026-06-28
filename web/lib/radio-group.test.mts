// Pure tests for the ARIA radio-group keyboard math (F128). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  isRadioNavKey,
  radioNavIndex,
  radioTabbableIndex,
} from "./radio-group.ts";

test("isRadioNavKey: arrows + Home/End are nav keys, others are not", () => {
  for (const k of [
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
  ]) {
    assert.equal(isRadioNavKey(k), true, k);
  }
  for (const k of ["Tab", " ", "Enter", "Escape", "a", "PageDown"]) {
    assert.equal(isRadioNavKey(k), false, k);
  }
});

test("radioNavIndex: Right/Down step forward with wrap", () => {
  assert.equal(radioNavIndex(0, 3, "ArrowRight"), 1);
  assert.equal(radioNavIndex(1, 3, "ArrowDown"), 2);
  // Wrap past the end back to the top.
  assert.equal(radioNavIndex(2, 3, "ArrowRight"), 0);
  assert.equal(radioNavIndex(2, 3, "ArrowDown"), 0);
});

test("radioNavIndex: Left/Up step backward with wrap", () => {
  assert.equal(radioNavIndex(2, 3, "ArrowLeft"), 1);
  assert.equal(radioNavIndex(1, 3, "ArrowUp"), 0);
  // Wrap past the top to the end.
  assert.equal(radioNavIndex(0, 3, "ArrowLeft"), 2);
  assert.equal(radioNavIndex(0, 3, "ArrowUp"), 2);
});

test("radioNavIndex: Home/End jump to the ends", () => {
  assert.equal(radioNavIndex(2, 3, "Home"), 0);
  assert.equal(radioNavIndex(0, 3, "End"), 2);
});

test("radioNavIndex: from no selection, forward lands first / backward lands last", () => {
  assert.equal(radioNavIndex(-1, 3, "ArrowRight"), 0);
  assert.equal(radioNavIndex(-1, 3, "ArrowDown"), 0);
  assert.equal(radioNavIndex(-1, 3, "ArrowLeft"), 2);
  assert.equal(radioNavIndex(-1, 3, "ArrowUp"), 2);
});

test("radioNavIndex: non-nav key or empty group returns null", () => {
  assert.equal(radioNavIndex(0, 3, "Tab"), null);
  assert.equal(radioNavIndex(0, 3, "x"), null);
  assert.equal(radioNavIndex(0, 0, "ArrowRight"), null);
});

test("radioNavIndex: a stale current index is clamped before stepping", () => {
  // current beyond the end clamps to the last item, so Right wraps to 0.
  assert.equal(radioNavIndex(9, 3, "ArrowRight"), 0);
  // ...and Left from the clamped last item goes to the second-to-last.
  assert.equal(radioNavIndex(9, 3, "ArrowLeft"), 1);
});

test("radioTabbableIndex: selected option is the tabbable one", () => {
  assert.equal(radioTabbableIndex(1, 3), 1);
  assert.equal(radioTabbableIndex(2, 3), 2);
});

test("radioTabbableIndex: nothing selected -> first option is tabbable", () => {
  assert.equal(radioTabbableIndex(-1, 3), 0);
  assert.equal(radioTabbableIndex(NaN, 3), 0);
});

test("radioTabbableIndex: a stale selected index clamps into range", () => {
  assert.equal(radioTabbableIndex(9, 3), 2);
});

test("radioTabbableIndex: empty group has no tabbable option", () => {
  assert.equal(radioTabbableIndex(0, 0), -1);
  assert.equal(radioTabbableIndex(-1, 0), -1);
  assert.equal(radioTabbableIndex(0, NaN), -1);
});
