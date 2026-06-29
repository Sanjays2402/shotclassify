// Pure tests for the /digest daily peak caption (F158). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { digestPeak, digestPeakCaption } from "./digest-peak.ts";

const week = [
  { date: "2026-05-10", count: 4 },
  { date: "2026-05-11", count: 9 },
  { date: "2026-05-12", count: 31 },
  { date: "2026-05-13", count: 12 },
];

test("digestPeak: finds the busiest day, total, avg", () => {
  const p = digestPeak(week);
  assert.ok(p);
  assert.equal(p.peakIndex, 2);
  assert.equal(p.peakDate, "2026-05-12");
  assert.equal(p.peakCount, 31);
  assert.equal(p.total, 56);
  assert.equal(p.avgPerDay, 14);
  assert.equal(p.days, 4);
});

test("digestPeak: first peak on ties, ignores junk counts", () => {
  const p = digestPeak([
    { date: "a", count: 5 },
    { date: "b", count: 5 },
    { date: "c", count: NaN },
  ]);
  assert.ok(p);
  assert.equal(p.peakIndex, 0);
  assert.equal(p.total, 10);
});

test("digestPeak: null for empty", () => {
  assert.equal(digestPeak([]), null);
  assert.equal(digestPeak(null), null);
});

test("digestPeakCaption: names day, singular shot, quiet when zero", () => {
  assert.match(digestPeakCaption(digestPeak(week)) ?? "", /Busiest 2026-05-12 · 31 shots/);
  assert.equal(digestPeakCaption(digestPeak([{ date: "x", count: 1 }])), "Busiest x · 1 shot · 1/day avg");
  assert.equal(digestPeakCaption(digestPeak([{ date: "x", count: 0 }])), "No activity in this window");
  assert.equal(digestPeakCaption(null), "No activity in this window");
});
