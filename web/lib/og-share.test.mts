import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ogTierColor,
  ogFmtFilename,
  ogTopThree,
  ogBarWidthPct,
} from "./og-share";

test("ogTierColor buckets confidence into 3 tiers", () => {
  assert.equal(ogTierColor(0.95), "#34d399");
  assert.equal(ogTierColor(0.8), "#34d399");
  assert.equal(ogTierColor(0.7), "#fbbf24");
  assert.equal(ogTierColor(0.55), "#fbbf24");
  assert.equal(ogTierColor(0.4), "#fb7185");
  assert.equal(ogTierColor(0), "#fb7185");
});

test("ogFmtFilename truncates long names in the middle", () => {
  assert.equal(ogFmtFilename("short.png"), "short.png");
  const long = "a".repeat(30) + "MIDDLE" + "b".repeat(30);
  const out = ogFmtFilename(long);
  assert.ok(out.includes("..."));
  assert.ok(out.length <= 48);
  assert.ok(out.startsWith("a"));
  assert.ok(out.endsWith("b"));
});

test("ogTopThree returns top 3 by score, descending", () => {
  const list = [
    { category: "a", score: 0.1 },
    { category: "b", score: 0.9 },
    { category: "c", score: 0.5 },
    { category: "d", score: 0.7 },
  ];
  const out = ogTopThree(list);
  assert.equal(out.length, 3);
  assert.deepEqual(
    out.map((x) => x.category),
    ["b", "d", "c"],
  );
});

test("ogTopThree handles empty/undefined input", () => {
  assert.deepEqual(ogTopThree(undefined), []);
  assert.deepEqual(ogTopThree([]), []);
});

test("ogBarWidthPct clamps and floors", () => {
  assert.equal(ogBarWidthPct(0), 6);
  assert.equal(ogBarWidthPct(-1), 6);
  assert.equal(ogBarWidthPct(0.5), 50);
  assert.equal(ogBarWidthPct(1), 100);
  assert.equal(ogBarWidthPct(2), 100);
  assert.equal(ogBarWidthPct(Number.NaN), 6);
});
