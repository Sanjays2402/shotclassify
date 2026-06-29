// Pure tests for the /usage month-end spend projection (F166). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { projectUsage, projectionCaption } from "./usage-projection.ts";

// A 10-day period for easy fractions.
const START = Date.parse("2026-06-01T00:00:00Z");
const END = Date.parse("2026-06-11T00:00:00Z");
const day = (n: number) => START + n * 24 * 3600 * 1000;

test("projectUsage: halfway through, doubles the run rate", () => {
  // 5 of 10 days elapsed, 4000 used -> projects 8000.
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 4000,
    limit: 10000,
    now: day(5),
  });
  assert.equal(p.ok, true);
  assert.equal(p.elapsedFraction, 0.5);
  assert.equal(p.projectedTotal, 8000);
  assert.equal(p.willExceed, false);
  assert.equal(p.projectedPercentOfLimit, 0.8);
});

test("projectUsage: a hot pace projects over the limit", () => {
  // 2 of 10 days, 3000 used -> projects 15000 > 10000.
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 3000,
    limit: 10000,
    now: day(2),
  });
  assert.equal(p.projectedTotal, 15000);
  assert.equal(p.willExceed, true);
  assert.equal(p.projectedPercentOfLimit, 1.5);
});

test("projectUsage: before any time elapses -> not ok (no rate yet)", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 0,
    limit: 10000,
    now: START,
  });
  assert.equal(p.ok, false);
  assert.equal(p.projectedTotal, null);
});

test("projectUsage: now clamped to period end -> projects the final total", () => {
  // Past the end with 9000 used: clamps to fraction 1.0, projects 9000 (not
  // an under-shoot from a >1 divisor).
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 9000,
    limit: 10000,
    now: day(20),
  });
  assert.equal(p.elapsedFraction, 1);
  assert.equal(p.projectedTotal, 9000);
  assert.equal(p.willExceed, false);
});

test("projectUsage: now before start clamps to no-elapsed -> not ok", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 100,
    limit: 10000,
    now: START - 5000,
  });
  assert.equal(p.ok, false);
});

test("projectUsage: projection never under-shoots what's already used", () => {
  // 9.9 of 10 days, 5000 used: used/0.99 = 5050, still >= used. But a case
  // where rounding could dip below used must clamp up.
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 5000,
    limit: 10000,
    now: day(9.9),
  });
  assert.ok(p.projectedTotal! >= 5000);
});

test("projectUsage: degenerate period (zero width) -> not ok", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: START,
    used: 10,
    limit: 100,
    now: START,
  });
  assert.equal(p.ok, false);
});

test("projectUsage: unparseable timestamps -> not ok", () => {
  const p = projectUsage({
    periodStart: "not-a-date",
    periodEnd: END,
    used: 10,
    limit: 100,
    now: day(1),
  });
  assert.equal(p.ok, false);
});

test("projectUsage: non-positive limit yields null percent, no exceed", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 500,
    limit: 0,
    now: day(5),
  });
  assert.equal(p.ok, true);
  assert.equal(p.projectedPercentOfLimit, null);
  assert.equal(p.willExceed, false);
});

test("projectUsage: negative used coerced to zero", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: -50,
    limit: 100,
    now: day(5),
  });
  assert.equal(p.projectedTotal, 0);
});

test("projectionCaption: under-limit names the pace and the cap", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 4000,
    limit: 10000,
    now: day(5),
  });
  assert.equal(
    projectionCaption(p, 10000, "Jun 11"),
    "On pace for ~8,000 of 10,000 by Jun 11.",
  );
});

test("projectionCaption: over-limit warns it will exceed", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 3000,
    limit: 10000,
    now: day(2),
  });
  assert.equal(
    projectionCaption(p, 10000, "Jun 11"),
    "On pace to exceed the limit (~15,000) before Jun 11.",
  );
});

test("projectionCaption: not-ok projection yields an empty string", () => {
  const p = projectUsage({
    periodStart: START,
    periodEnd: END,
    used: 0,
    limit: 10000,
    now: START,
  });
  assert.equal(projectionCaption(p, 10000, "Jun 11"), "");
});
