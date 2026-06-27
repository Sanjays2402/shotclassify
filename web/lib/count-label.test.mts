// Pure tests for the shared "N of M <noun>" count-label helper (F112). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { ofTotalLabel } from "./count-label.ts";

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
