// Pure tests for the compact number formatter (KPI / ticker / quota). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { compactNumber, fullNumber, isCompacted } from "./num-compact.ts";

test("compactNumber: sub-thousand stays exact, no suffix", () => {
  assert.equal(compactNumber(0), "0");
  assert.equal(compactNumber(7), "7");
  assert.equal(compactNumber(999), "999");
});

test("compactNumber: thousands abbreviate to K with trimmed .0", () => {
  assert.equal(compactNumber(1000), "1K");
  assert.equal(compactNumber(1234), "1.2K");
  assert.equal(compactNumber(12345), "12.3K");
  assert.equal(compactNumber(999999), "1000K");
});

test("compactNumber: millions / billions / trillions", () => {
  assert.equal(compactNumber(1_200_000), "1.2M");
  assert.equal(compactNumber(3_400_000_000), "3.4B");
  assert.equal(compactNumber(5_600_000_000_000), "5.6T");
});

test("compactNumber: negatives keep sign, junk -> 0", () => {
  assert.equal(compactNumber(-1500), "-1.5K");
  assert.equal(compactNumber(-42), "-42");
  assert.equal(compactNumber(NaN), "0");
  assert.equal(compactNumber(null), "0");
  assert.equal(compactNumber(undefined), "0");
});

test("fullNumber: grouped exact figure for the tooltip", () => {
  assert.equal(fullNumber(12345), (12345).toLocaleString());
  assert.equal(fullNumber(7.9), "7");
  assert.equal(fullNumber(null), "0");
});

test("isCompacted: only true once a suffix appears", () => {
  assert.equal(isCompacted(999), false);
  assert.equal(isCompacted(1000), true);
  assert.equal(isCompacted(-2000), true);
  assert.equal(isCompacted(NaN), false);
});
