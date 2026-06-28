// Pure tests for the shared "N of M <noun>" count-label helper (F112). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { ofTotalLabel, rangeOfTotalLabel, countLabel } from "./count-label.ts";

test("ofTotalLabel: webhooks shape -- prefix + plural noun, narrowed", () => {
  const opts = { prefix: "Filtering ", singular: "delivery", plural: "deliveries" };
  assert.equal(ofTotalLabel(3, 10, opts), "Filtering 3 of 10 deliveries");
  assert.equal(ofTotalLabel(0, 4, opts), "Filtering 0 of 4 deliveries");
});

test("ofTotalLabel: webhooks shape -- singular noun at a total of one", () => {
  const opts = { prefix: "Filtering ", singular: "delivery", plural: "deliveries" };
  assert.equal(ofTotalLabel(0, 1, opts), "Filtering 0 of 1 delivery");
});

test("ofTotalLabel: default onlyWhenNarrowed hides an un-narrowed view", () => {
  const opts = { prefix: "Filtering ", singular: "delivery", plural: "deliveries" };
  assert.equal(ofTotalLabel(10, 10, opts), null);
  assert.equal(ofTotalLabel(0, 0, opts), null);
});

test("ofTotalLabel: notifications shape -- no prefix, fixed noun, always shown", () => {
  const opts = { singular: "match", onlyWhenNarrowed: false };
  // The notifications line uses a fixed "match" for both singular and plural
  // (no `plural` -> defaults to singular) and shows even when nothing is hidden.
  assert.equal(ofTotalLabel(3, 10, opts), "3 of 10 match");
  assert.equal(ofTotalLabel(10, 10, opts), "10 of 10 match");
  assert.equal(ofTotalLabel(1, 1, opts), "1 of 1 match");
});

test("ofTotalLabel: plural defaults to singular when omitted", () => {
  const opts = { singular: "item", onlyWhenNarrowed: false };
  assert.equal(ofTotalLabel(2, 5, opts), "2 of 5 item");
  assert.equal(ofTotalLabel(0, 1, opts), "0 of 1 item");
});

test("ofTotalLabel: shown is clamped into [0, total]", () => {
  const opts = { singular: "row", plural: "rows", onlyWhenNarrowed: false };
  // shown > total clamps to total.
  assert.equal(ofTotalLabel(12, 10, opts), "10 of 10 rows");
  // negative shown floors at zero.
  assert.equal(ofTotalLabel(-3, 5, opts), "0 of 5 rows");
});

test("ofTotalLabel: clamped-to-total reads as un-narrowed under default", () => {
  const opts = { prefix: "Filtering ", singular: "delivery", plural: "deliveries" };
  // shown > total clamps to total -> s >= t -> null when onlyWhenNarrowed.
  assert.equal(ofTotalLabel(12, 10, opts), null);
});

test("ofTotalLabel: fractional inputs truncate toward zero", () => {
  const opts = { singular: "row", plural: "rows", onlyWhenNarrowed: false };
  assert.equal(ofTotalLabel(2.9, 9.4, opts), "2 of 9 rows");
});

test("ofTotalLabel: non-finite inputs no-op to null", () => {
  const opts = { singular: "row", plural: "rows", onlyWhenNarrowed: false };
  assert.equal(ofTotalLabel(NaN, 5, opts), null);
  assert.equal(ofTotalLabel(2, Infinity, opts), null);
  assert.equal(ofTotalLabel(-Infinity, 5, opts), null);
});

test("ofTotalLabel: negative total floors at zero -> null under default", () => {
  const opts = { prefix: "Filtering ", singular: "delivery", plural: "deliveries" };
  assert.equal(ofTotalLabel(0, -4, opts), null);
});

test("rangeOfTotalLabel: normal page range uses an en dash + ' of '", () => {
  assert.equal(rangeOfTotalLabel(1, 50, 1240), "1\u201350 of 1240");
  assert.equal(rangeOfTotalLabel(51, 100, 1240), "51\u2013100 of 1240");
});

test("rangeOfTotalLabel: a final partial page clamps the upper bound to total", () => {
  // page 25 of a 50/page list over 1240 rows: 1201..1250 but only 1240 exist.
  assert.equal(rangeOfTotalLabel(1201, 1250, 1240), "1201\u20131240 of 1240");
});

test("rangeOfTotalLabel: bounds clamp into [1, total]; from never exceeds to", () => {
  // Over-range from is pulled down to the (clamped) to.
  assert.equal(rangeOfTotalLabel(99, 40, 50), "40\u201340 of 50");
  // Zero / negative from floors at 1.
  assert.equal(rangeOfTotalLabel(0, 10, 50), "1\u201310 of 50");
  assert.equal(rangeOfTotalLabel(-5, 10, 50), "1\u201310 of 50");
});

test("rangeOfTotalLabel: empty list (total <= 0) -> null", () => {
  assert.equal(rangeOfTotalLabel(0, 0, 0), null);
  assert.equal(rangeOfTotalLabel(1, 50, -3), null);
});

test("rangeOfTotalLabel: non-finite inputs -> null", () => {
  assert.equal(rangeOfTotalLabel(NaN, 50, 100), null);
  assert.equal(rangeOfTotalLabel(1, Infinity, 100), null);
  assert.equal(rangeOfTotalLabel(1, 50, NaN), null);
});

test("rangeOfTotalLabel: fractional bounds truncate toward zero", () => {
  assert.equal(rangeOfTotalLabel(1.9, 50.9, 100.4), "1\u201350 of 100");
});

test("countLabel: singular at one, auto -s plural otherwise", () => {
  assert.equal(countLabel(1, "row"), "1 row");
  assert.equal(countLabel(0, "row"), "0 rows");
  assert.equal(countLabel(12, "row"), "12 rows");
});

test("countLabel: explicit irregular plural is honoured", () => {
  assert.equal(countLabel(1, "match", "matches"), "1 match");
  assert.equal(countLabel(3, "match", "matches"), "3 matches");
});

test("countLabel: non-finite / negative floors at zero, fractional truncates", () => {
  assert.equal(countLabel(NaN, "row"), "0 rows");
  assert.equal(countLabel(-4, "row"), "0 rows");
  assert.equal(countLabel(2.9, "row"), "2 rows");
});
