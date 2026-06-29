// Pure tests for the class-mix tooltip formatter (F157). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  classMixCountText,
  classMixConfText,
  classMixTooltipFormatter,
} from "./class-mix-tooltip.ts";

test("classMixCountText: pluralises and floors to whole shots", () => {
  assert.equal(classMixCountText(12), "12 shots");
  assert.equal(classMixCountText(1), "1 shot");
  assert.equal(classMixCountText(0), "0 shots");
  assert.equal(classMixCountText(2.6), "3 shots");
});

test("classMixCountText: thousands separator, guards bad input", () => {
  assert.equal(classMixCountText(1200), "1,200 shots");
  assert.equal(classMixCountText(-4), "0 shots");
  assert.equal(classMixCountText(NaN), "0 shots");
});

test("classMixConfText: rounds whole-percent mean, guards missing", () => {
  assert.equal(classMixConfText(87), "87% conf");
  assert.equal(classMixConfText(87.4), "87% conf");
  assert.equal(classMixConfText(0), "0% conf");
  assert.equal(classMixConfText(null), "0% conf");
  assert.equal(classMixConfText(undefined), "0% conf");
  assert.equal(classMixConfText(NaN), "0% conf");
});

test("classMixTooltipFormatter: folds count + conf into one row", () => {
  assert.deepEqual(classMixTooltipFormatter(12, { mean: 87 }), [
    "12 shots \u00b7 87% conf",
    "Class mix",
  ]);
  assert.deepEqual(classMixTooltipFormatter(1, { mean: 92 }), [
    "1 shot \u00b7 92% conf",
    "Class mix",
  ]);
});

test("classMixTooltipFormatter: tolerates absent datum / mean", () => {
  assert.deepEqual(classMixTooltipFormatter(5, undefined), [
    "5 shots \u00b7 0% conf",
    "Class mix",
  ]);
  assert.deepEqual(classMixTooltipFormatter(5, {}), [
    "5 shots \u00b7 0% conf",
    "Class mix",
  ]);
});
