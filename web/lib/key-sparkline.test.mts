// Pure tests for the /keys/[id] sparkline geometry (F140). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  cleanSeries,
  sparklineGeometry,
  summarizeSeries,
} from "./key-sparkline.ts";

test("cleanSeries: drops junk, floors negatives/NaN, stringifies day", () => {
  const s = cleanSeries([
    { day: "2024-01-01", count: 5 },
    // @ts-expect-error -- malformed members
    null,
    { day: "2024-01-02", count: -3 },
    // @ts-expect-error -- non-finite count
    { day: "2024-01-03", count: "x" },
    { day: "2024-01-04", count: 2.9 },
  ]);
  assert.deepEqual(s, [
    { day: "2024-01-01", count: 5 },
    { day: "2024-01-02", count: 0 },
    { day: "2024-01-03", count: 0 },
    { day: "2024-01-04", count: 2 },
  ]);
});

test("cleanSeries: a non-array is an empty series", () => {
  assert.deepEqual(cleanSeries(null), []);
  // @ts-expect-error -- wrong type on purpose.
  assert.deepEqual(cleanSeries("nope"), []);
});

test("sparklineGeometry: empty series yields empty paths and peak 1", () => {
  const g = sparklineGeometry([]);
  assert.equal(g.linePath, "");
  assert.equal(g.areaPath, "");
  assert.equal(g.peak, 1);
  assert.equal(g.points.length, 0);
  assert.equal(g.firstDay, "");
  assert.equal(g.lastDay, "");
});

test("sparklineGeometry: single point pins to the left edge", () => {
  const g = sparklineGeometry([{ day: "d1", count: 7 }], { width: 100, padX: 8 });
  assert.equal(g.points.length, 1);
  assert.equal(g.points[0].x, 8);
  assert.ok(g.linePath.startsWith("M "));
  assert.equal(g.peak, 7);
});

test("sparklineGeometry: peak floored at 1 so all-zero is flat baseline", () => {
  const g = sparklineGeometry([
    { day: "a", count: 0 },
    { day: "b", count: 0 },
  ], { height: 96, padY: 12 });
  assert.equal(g.peak, 1);
  // every point sits on the baseline (height - padY)
  for (const p of g.points) assert.equal(p.y, 84);
});

test("sparklineGeometry: endpoints span the full inner width", () => {
  const g = sparklineGeometry(
    [
      { day: "a", count: 1 },
      { day: "b", count: 2 },
      { day: "c", count: 3 },
    ],
    { width: 720, padX: 8 },
  );
  assert.equal(g.points[0].x, 8);
  assert.equal(g.points[2].x, 712);
  assert.equal(g.firstDay, "a");
  assert.equal(g.lastDay, "c");
  assert.ok(g.areaPath.endsWith("Z"));
});

test("summarizeSeries: total/peak/busiest with left-most tie-break", () => {
  const s = summarizeSeries([
    { day: "a", count: 4 },
    { day: "b", count: 9 },
    { day: "c", count: 9 },
  ]);
  assert.equal(s.total, 22);
  assert.equal(s.peak, 9);
  assert.equal(s.busiestDay, "b"); // first of the tied peaks
  assert.equal(s.hasTraffic, true);
});

test("summarizeSeries: all-zero reports no traffic, blank busiest day", () => {
  const s = summarizeSeries([{ day: "a", count: 0 }]);
  assert.deepEqual(s, { total: 0, peak: 0, busiestDay: "", hasTraffic: false });
});
