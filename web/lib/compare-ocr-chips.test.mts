// Pure tests for the /compare OCR-stat chip helpers (F171). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  ocrWordCount,
  ocrMeanConfidence,
  ocrChips,
} from "./compare-ocr-chips.ts";

test("ocrWordCount: prefers the payload's own count", () => {
  assert.equal(ocrWordCount({ word_count: 212, text: "a b c" }), 212);
});

test("ocrWordCount: falls back to splitting text when count absent", () => {
  assert.equal(ocrWordCount({ text: "  one two   three " }), 3);
});

test("ocrWordCount: empty text is zero words, not null", () => {
  assert.equal(ocrWordCount({ text: "   " }), 0);
});

test("ocrWordCount: no count and no text -> null", () => {
  assert.equal(ocrWordCount({}), null);
  assert.equal(ocrWordCount(null), null);
  assert.equal(ocrWordCount(undefined), null);
});

test("ocrWordCount: a fractional count is truncated", () => {
  assert.equal(ocrWordCount({ word_count: 4.9 }), 4);
});

test("ocrWordCount: a negative count is rejected, falls through to text", () => {
  assert.equal(ocrWordCount({ word_count: -1, text: "x y" }), 2);
  // No text either -> null.
  assert.equal(ocrWordCount({ word_count: -1 }), null);
});

test("ocrMeanConfidence: clamps to 0..1", () => {
  assert.equal(ocrMeanConfidence({ mean_confidence: 0.91 }), 0.91);
  assert.equal(ocrMeanConfidence({ mean_confidence: 1.4 }), 1);
  assert.equal(ocrMeanConfidence({ mean_confidence: -0.2 }), 0);
});

test("ocrMeanConfidence: absent / non-finite -> null", () => {
  assert.equal(ocrMeanConfidence({}), null);
  assert.equal(ocrMeanConfidence({ mean_confidence: NaN }), null);
  assert.equal(ocrMeanConfidence(null), null);
});

test("ocrChips: both stats present -> two chips, formatted", () => {
  const chips = ocrChips({ word_count: 1234, mean_confidence: 0.91 });
  assert.equal(chips.length, 2);
  assert.deepEqual(chips[0], { key: "words", label: "Words", value: "1,234" });
  assert.equal(chips[1].key, "legibility");
  assert.equal(chips[1].value, "91%");
  assert.equal(chips[1].score, 0.91);
});

test("ocrChips: zero words is shown (a meaningful fact)", () => {
  const chips = ocrChips({ text: "" });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].value, "0");
});

test("ocrChips: image-only shot (no count, no conf) -> empty list", () => {
  assert.deepEqual(ocrChips({}), []);
  assert.deepEqual(ocrChips(null), []);
});

test("ocrChips: legibility-only block still yields one chip", () => {
  const chips = ocrChips({ mean_confidence: 0.5 });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].key, "legibility");
  assert.equal(chips[0].value, "50%");
});

test("ocrChips: confidence rounds to a whole percent", () => {
  assert.equal(ocrChips({ mean_confidence: 0.875 })[0].value, "88%");
  assert.equal(ocrChips({ mean_confidence: 0.014 })[0].value, "1%");
});
