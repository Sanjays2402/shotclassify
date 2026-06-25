// Pure tests for the skeleton geometry + ragged-width helpers. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  toCssSize,
  resolveShape,
  raggedWidths,
  VARIANT_SHAPES,
} from "./skeleton.ts";

test("toCssSize: numbers become px, strings pass through, undefined falls back", () => {
  assert.equal(toCssSize(120, "100%"), "120px");
  assert.equal(toCssSize("60%", "100%"), "60%");
  assert.equal(toCssSize(undefined, "100%"), "100%");
  assert.equal(toCssSize(0, "100%"), "0px");
});

test("resolveShape: returns variant defaults when no overrides", () => {
  for (const v of Object.keys(VARIANT_SHAPES) as (keyof typeof VARIANT_SHAPES)[]) {
    const s = resolveShape(v);
    assert.equal(s.height, VARIANT_SHAPES[v].height);
    assert.equal(s.width, VARIANT_SHAPES[v].width);
    assert.equal(s.radius, VARIANT_SHAPES[v].radius);
  }
});

test("resolveShape: overrides win and coerce", () => {
  const s = resolveShape("text", { width: 200, height: "2em", radius: 8 });
  assert.equal(s.width, "200px");
  assert.equal(s.height, "2em");
  assert.equal(s.radius, 8);
});

test("resolveShape: circle has a pill radius by default", () => {
  assert.equal(resolveShape("circle").radius, 9999);
});

test("raggedWidths: count<=0 yields empty, count===1 yields full width", () => {
  assert.deepEqual(raggedWidths(0), []);
  assert.deepEqual(raggedWidths(-3), []);
  assert.deepEqual(raggedWidths(1), ["100%"]);
});

test("raggedWidths: deterministic for a given seed (no hydration drift)", () => {
  const a = raggedWidths(5, 42);
  const b = raggedWidths(5, 42);
  assert.deepEqual(a, b);
});

test("raggedWidths: different seeds usually differ", () => {
  const a = raggedWidths(5, 1);
  const b = raggedWidths(5, 999);
  assert.notDeepEqual(a, b);
});

test("raggedWidths: every width is a percent within the expected band", () => {
  const widths = raggedWidths(6, 7);
  for (let i = 0; i < widths.length - 1; i++) {
    const n = Number(widths[i].replace("%", ""));
    assert.ok(n >= 62 && n <= 95, `width ${widths[i]} out of band`);
  }
  // Final line is forced short to read like end-of-paragraph.
  assert.equal(widths[widths.length - 1], "48%");
});
