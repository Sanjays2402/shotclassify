// Pure tests for the minConf threshold label helper (F156). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { hasConfFloorPct, confFloorLabel, confFloorReadout } from "./conf-floor.ts";

test("hasConfFloorPct: positive is a floor, zero / negative / bad is not", () => {
  assert.equal(hasConfFloorPct(80), true);
  assert.equal(hasConfFloorPct(0), false);
  assert.equal(hasConfFloorPct(-5), false);
  assert.equal(hasConfFloorPct(NaN), false);
  assert.equal(hasConfFloorPct(null), false);
  assert.equal(hasConfFloorPct(undefined), false);
});

test("confFloorLabel: whole percent renders as a two-decimal fraction", () => {
  assert.equal(confFloorLabel(80), "conf \u2265 0.80");
  assert.equal(confFloorLabel(55), "conf \u2265 0.55");
  assert.equal(confFloorLabel(5), "conf \u2265 0.05");
});

test("confFloorLabel: 0 / non-finite -> null so the chip stays hidden", () => {
  assert.equal(confFloorLabel(0), null);
  assert.equal(confFloorLabel(null), null);
  assert.equal(confFloorLabel(NaN), null);
});

test("confFloorLabel: over-100 clamps to 1.00", () => {
  assert.equal(confFloorLabel(140), "conf \u2265 1.00");
});

test("confFloorReadout: 'any' at rest, the label when narrowed", () => {
  assert.equal(confFloorReadout(0), "any");
  assert.equal(confFloorReadout(80), "conf \u2265 0.80");
});
