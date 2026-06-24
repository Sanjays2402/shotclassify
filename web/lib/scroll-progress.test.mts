// Pure tests for the scroll-progress math.
import test from "node:test";
import assert from "node:assert/strict";

import { backToTopVisible, scrollProgress } from "./scroll-progress.ts";

test("scrollProgress: 0 at top, 1 at bottom, monotonic between", () => {
  // Page is 4000 tall, viewport 1000 tall, scroll 0 -> 0%, max scroll = 3000.
  assert.equal(scrollProgress(0, 4000, 1000), 0);
  assert.equal(scrollProgress(1500, 4000, 1000), 0.5);
  assert.equal(scrollProgress(3000, 4000, 1000), 1);
});

test("scrollProgress: clamps overscroll bounce on either side", () => {
  // iOS / macOS rubber-band scroll can report scrollTop slightly negative
  // or above the max for a frame or two.
  assert.equal(scrollProgress(-50, 4000, 1000), 0);
  assert.equal(scrollProgress(4500, 4000, 1000), 1);
});

test("scrollProgress: defends against non-scrollable pages", () => {
  // Page shorter than viewport.
  assert.equal(scrollProgress(0, 500, 1000), 0);
  // scrollHeight === clientHeight -> nothing to scroll.
  assert.equal(scrollProgress(0, 1000, 1000), 0);
});

test("scrollProgress: rejects non-finite inputs", () => {
  assert.equal(scrollProgress(NaN, 4000, 1000), 0);
  assert.equal(scrollProgress(Infinity, 4000, 1000), 0);
  assert.equal(scrollProgress(500, NaN, 1000), 0);
  assert.equal(scrollProgress(500, 4000, NaN), 0);
});

test("backToTopVisible: hidden below threshold, visible above", () => {
  assert.equal(backToTopVisible(0), false);
  assert.equal(backToTopVisible(599), false);
  assert.equal(backToTopVisible(600), false);
  assert.equal(backToTopVisible(601), true);
});

test("backToTopVisible: custom threshold respected", () => {
  assert.equal(backToTopVisible(200, 100), true);
  assert.equal(backToTopVisible(50, 100), false);
});

test("backToTopVisible: NaN scroll yields hidden", () => {
  assert.equal(backToTopVisible(NaN), false);
});
