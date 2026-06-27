// Pure tests for the roving-tabindex helper (F114). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { rovingIndex, isRovingKey } from "./roving-index.ts";

test("isRovingKey: only the four navigation keys", () => {
  for (const k of ["ArrowDown", "ArrowUp", "Home", "End"]) {
    assert.equal(isRovingKey(k), true, k);
  }
  for (const k of ["Enter", "Escape", "a", "ArrowLeft", "Tab", ""]) {
    assert.equal(isRovingKey(k), false, k);
  }
});

test("rovingIndex: non-navigation key -> null", () => {
  assert.equal(rovingIndex(0, 3, "Enter"), null);
  assert.equal(rovingIndex(0, 3, "Escape"), null);
  assert.equal(rovingIndex(0, 3, "x"), null);
});

test("rovingIndex: empty / invalid list -> null", () => {
  assert.equal(rovingIndex(0, 0, "ArrowDown"), null);
  assert.equal(rovingIndex(0, -2, "ArrowDown"), null);
  assert.equal(rovingIndex(0, NaN, "ArrowDown"), null);
});

test("rovingIndex: ArrowDown steps forward and wraps", () => {
  assert.equal(rovingIndex(0, 3, "ArrowDown"), 1);
  assert.equal(rovingIndex(1, 3, "ArrowDown"), 2);
  // wrap past the end back to the top
  assert.equal(rovingIndex(2, 3, "ArrowDown"), 0);
});

test("rovingIndex: ArrowUp steps backward and wraps", () => {
  assert.equal(rovingIndex(2, 3, "ArrowUp"), 1);
  assert.equal(rovingIndex(1, 3, "ArrowUp"), 0);
  // wrap past the top to the end
  assert.equal(rovingIndex(0, 3, "ArrowUp"), 2);
});

test("rovingIndex: from an unfocused state, Down -> first, Up -> last", () => {
  for (const unfocused of [-1, -5, NaN]) {
    assert.equal(rovingIndex(unfocused as number, 3, "ArrowDown"), 0, `${unfocused}`);
    assert.equal(rovingIndex(unfocused as number, 3, "ArrowUp"), 2, `${unfocused}`);
  }
});

test("rovingIndex: Home / End jump to the ends", () => {
  assert.equal(rovingIndex(2, 4, "Home"), 0);
  assert.equal(rovingIndex(0, 4, "End"), 3);
  // from unfocused too
  assert.equal(rovingIndex(-1, 4, "Home"), 0);
  assert.equal(rovingIndex(-1, 4, "End"), 3);
});

test("rovingIndex: a stale over-range index is clamped before stepping", () => {
  // List shrank to 3 but current still says 9: clamp to last (2), then step.
  assert.equal(rovingIndex(9, 3, "ArrowDown"), 0); // 2 -> wrap -> 0
  assert.equal(rovingIndex(9, 3, "ArrowUp"), 1); // 2 -> 1
});

test("rovingIndex: single-item list wraps to itself", () => {
  assert.equal(rovingIndex(0, 1, "ArrowDown"), 0);
  assert.equal(rovingIndex(0, 1, "ArrowUp"), 0);
  assert.equal(rovingIndex(0, 1, "Home"), 0);
  assert.equal(rovingIndex(0, 1, "End"), 0);
});

test("rovingIndex: fractional inputs truncate", () => {
  assert.equal(rovingIndex(1.9, 3.5, "ArrowDown"), 2);
  assert.equal(rovingIndex(0.4, 3.5, "ArrowUp"), 2);
});
