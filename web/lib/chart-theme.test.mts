// Pure tests for the theme-aware recharts token set. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { chartTheme, axisTick, deltaStroke, deltaFill } from "./chart-theme.ts";

test("chartTheme: dim and light resolve to distinct palettes", () => {
  const light = chartTheme("light");
  const dim = chartTheme("dim");
  assert.notEqual(light.axisStroke, dim.axisStroke);
  assert.notEqual(light.gridStroke, dim.gridStroke);
  assert.notEqual(light.tickFill, dim.tickFill);
  assert.notEqual(light.cursorFill, dim.cursorFill);
});

test("chartTheme: light strokes are ink-based, dim strokes are chalk-based", () => {
  const light = chartTheme("light");
  const dim = chartTheme("dim");
  // Light uses the near-black ink rgb(11,15,12); dim uses chalk rgb(232,226,204).
  assert.match(light.axisStroke, /11,\s*15,\s*12/);
  assert.match(dim.axisStroke, /232,\s*226,\s*204/);
});

test("chartTheme: unknown / null input falls back to the light palette", () => {
  const light = chartTheme("light");
  assert.deepEqual(chartTheme(null), light);
  assert.deepEqual(chartTheme(undefined), light);
  assert.deepEqual(chartTheme("system"), light);
  assert.deepEqual(chartTheme(""), light);
});

test("chartTheme: tooltip card stays dark-on-light in BOTH themes", () => {
  // The broadcast tooltip is intentionally theme-stable so it never flips
  // to light-text-on-light-card under dim.
  for (const t of ["light", "dim"] as const) {
    const { tooltip } = chartTheme(t);
    assert.equal(tooltip.background, "#0B0F0C");
    assert.equal(tooltip.color, "#F2EBD8");
    assert.equal(tooltip.fontFamily, "var(--font-mono)");
  }
});

test("chartTheme: faint axis stroke is present and differs from the main one", () => {
  const dim = chartTheme("dim");
  assert.ok(dim.axisStrokeFaint);
  assert.notEqual(dim.axisStrokeFaint, dim.axisStroke);
});

test("axisTick: builds a recharts tick bag from the theme fill", () => {
  const dim = chartTheme("dim");
  const tick = axisTick(dim);
  assert.equal(tick.fill, dim.tickFill);
  assert.equal(tick.fontFamily, "var(--font-mono)");
  assert.equal(tick.fontSize, 10);
  // Custom font size flows through.
  assert.equal(axisTick(dim, 12).fontSize, 12);
});

test("chartTheme: delta + zeroLine tokens exist and differ per theme", () => {
  const light = chartTheme("light");
  const dim = chartTheme("dim");
  for (const t of [light, dim]) {
    assert.ok(t.positiveStroke);
    assert.ok(t.negativeStroke);
    assert.ok(t.positiveFill);
    assert.ok(t.negativeFill);
    assert.ok(t.zeroLine);
    // Rising vs falling must be visually distinct or the colour-coding is moot.
    assert.notEqual(t.positiveStroke, t.negativeStroke);
  }
  // Dim brightens the strokes so they lift off the dark panel -> not equal.
  assert.notEqual(light.positiveStroke, dim.positiveStroke);
  assert.notEqual(light.negativeStroke, dim.negativeStroke);
  assert.notEqual(light.zeroLine, dim.zeroLine);
});

test("deltaStroke: positive/zero -> positive colour, negative -> negative colour", () => {
  const t = chartTheme("light");
  assert.equal(deltaStroke(t, 0.5), t.positiveStroke);
  assert.equal(deltaStroke(t, 0), t.positiveStroke); // flat reads as fine, not bad
  assert.equal(deltaStroke(t, -0.3), t.negativeStroke);
});

test("deltaStroke: a non-finite delta falls back to the neutral zero line", () => {
  const t = chartTheme("dim");
  assert.equal(deltaStroke(t, NaN), t.zeroLine);
  assert.equal(deltaStroke(t, Infinity), t.zeroLine);
});

test("deltaFill: mirrors deltaStroke direction; non-finite is transparent", () => {
  const t = chartTheme("light");
  assert.equal(deltaFill(t, 2), t.positiveFill);
  assert.equal(deltaFill(t, 0), t.positiveFill);
  assert.equal(deltaFill(t, -1), t.negativeFill);
  assert.equal(deltaFill(t, NaN), "transparent");
});
