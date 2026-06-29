// Pure tests for the /compare diverging confidence-gap geometry (F161). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { confidenceGap, gapAriaLabel } from "./compare-gap.ts";

test("confidenceGap: B ahead yields a positive gap and b winner", () => {
  const g = confidenceGap(0.6, 0.82);
  assert.equal(g.aFill, 0.6);
  assert.equal(g.bFill, 0.82);
  assert.equal(g.deltaPts, 22); // (0.82 - 0.60) * 100
  assert.equal(g.absPts, 22);
  assert.equal(g.winner, "b");
});

test("confidenceGap: A ahead yields a negative gap and a winner", () => {
  const g = confidenceGap(0.9, 0.5);
  assert.equal(g.deltaPts, -40);
  assert.equal(g.absPts, 40);
  assert.equal(g.winner, "a");
});

test("confidenceGap: equal scores are a tie with a zero gap", () => {
  const g = confidenceGap(0.7, 0.7);
  assert.equal(g.deltaPts, 0);
  assert.equal(g.absPts, 0);
  assert.equal(g.winner, "tie");
});

test("confidenceGap: sub-0.05pt jitter rounds to a tie, no false winner", () => {
  // 0.7004 vs 0.7000 -> 0.04pt -> rounds to 0.0 -> tie, so the accent and the
  // printed "0.0 pts" agree.
  const g = confidenceGap(0.7, 0.7004);
  assert.equal(g.deltaPts, 0);
  assert.equal(g.winner, "tie");
});

test("confidenceGap: a real 0.1pt gap is kept and names a winner", () => {
  const g = confidenceGap(0.7, 0.701);
  assert.equal(g.deltaPts, 0.1);
  assert.equal(g.winner, "b");
});

test("confidenceGap: fills clamp to 0..1, gap uses the clamped values", () => {
  const g = confidenceGap(-0.5, 1.4);
  assert.equal(g.aFill, 0);
  assert.equal(g.bFill, 1);
  assert.equal(g.deltaPts, 100);
  assert.equal(g.winner, "b");
});

test("confidenceGap: non-finite / nullish sides collapse to 0 fill", () => {
  const g = confidenceGap(undefined, null as unknown as number);
  assert.equal(g.aFill, 0);
  assert.equal(g.bFill, 0);
  assert.equal(g.deltaPts, 0);
  assert.equal(g.winner, "tie");
});

test("confidenceGap: never emits negative zero in the gap", () => {
  const g = confidenceGap(0.50001, 0.5);
  // (0.5 - 0.50001)*100 = -0.001 -> rounds to 0, normalised away from -0.
  assert.ok(Object.is(g.deltaPts, 0));
  assert.equal(g.winner, "tie");
});

test("gapAriaLabel: names the leading side and pluralises points", () => {
  assert.equal(
    gapAriaLabel(confidenceGap(0.6, 0.82)),
    "Shot B is 22 points more confident",
  );
  assert.equal(
    gapAriaLabel(confidenceGap(0.9, 0.5)),
    "Shot A is 40 points more confident",
  );
  assert.equal(
    gapAriaLabel(confidenceGap(0.7, 0.7)),
    "Both shots are equally confident",
  );
});

test("gapAriaLabel: a one-point gap uses the singular 'point'", () => {
  assert.equal(
    gapAriaLabel(confidenceGap(0.7, 0.71)),
    "Shot B is 1 point more confident",
  );
});
