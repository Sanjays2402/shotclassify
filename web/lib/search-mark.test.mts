// Pure tests for OCR search-result highlight segmentation. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { markMatches, hasMatch } from "./search-mark.ts";

test("markMatches: no query -> single plain segment", () => {
  assert.deepEqual(markMatches("hello world", ""), [
    { text: "hello world", match: false },
  ]);
  assert.deepEqual(markMatches("hello", null), [{ text: "hello", match: false }]);
});

test("markMatches: case-insensitive, preserves original casing", () => {
  assert.deepEqual(markMatches("Latte Order", "latte"), [
    { text: "Latte", match: true },
    { text: " Order", match: false },
  ]);
});

test("markMatches: multiple hits with surrounding plain runs", () => {
  assert.deepEqual(markMatches("ab cd ab", "ab"), [
    { text: "ab", match: true },
    { text: " cd ", match: false },
    { text: "ab", match: true },
  ]);
});

test("markMatches: empty text yields one empty plain segment", () => {
  assert.deepEqual(markMatches("", "x"), [{ text: "", match: false }]);
});

test("markMatches: non-overlapping, advances past each hit", () => {
  const segs = markMatches("aaaa", "aa");
  assert.equal(segs.filter((s) => s.match).length, 2);
  assert.equal(segs.map((s) => s.text).join(""), "aaaa");
});

test("hasMatch: substring presence, case-insensitive", () => {
  assert.equal(hasMatch("Receipt total", "TOTAL"), true);
  assert.equal(hasMatch("nope", "xyz"), false);
  assert.equal(hasMatch("any", ""), false);
});
