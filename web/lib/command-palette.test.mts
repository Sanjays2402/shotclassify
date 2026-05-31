import { test } from "node:test";
import assert from "node:assert/strict";
import { fuzzyScore, rankNav } from "./command-palette";

test("fuzzyScore: empty query yields neutral score", () => {
  assert.equal(fuzzyScore("", "Shots", "Browse history"), 1);
  assert.equal(fuzzyScore("   ", "Shots", "Browse history"), 1);
});

test("fuzzyScore: startsWith beats contains beats hint beats loose", () => {
  const a = fuzzyScore("sho", "Shots", "Browse history");
  const b = fuzzyScore("ot", "Shots", "Browse history");
  const c = fuzzyScore("history", "Shots", "Browse history");
  const d = fuzzyScore("sts", "Shots", "Browse calibration"); // loose s..t..s
  assert.ok(a > b, "startsWith > contains");
  assert.ok(b > c, "contains > hint");
  assert.ok(c > d, "hint > loose");
  assert.equal(fuzzyScore("zzz", "Shots", "Browse history"), 0);
});

test("fuzzyScore is case-insensitive", () => {
  assert.equal(
    fuzzyScore("SHO", "Shots", "Browse history"),
    fuzzyScore("sho", "Shots", "Browse history"),
  );
});

test("rankNav: empty query returns first N items in order", () => {
  const nav = [
    { id: "a", label: "Live", hint: "Realtime" },
    { id: "b", label: "Shots", hint: "Browse history" },
    { id: "c", label: "Upload", hint: "Classify" },
    { id: "d", label: "Pricing", hint: "Plans" },
  ];
  const r = rankNav("", nav, 3);
  assert.deepEqual(
    r.map((x) => x.id),
    ["a", "b", "c"],
  );
});

test("rankNav: ranks by score, filters zeros, respects limit", () => {
  const nav = [
    { id: "live", label: "Live", hint: "Realtime classifier" },
    { id: "shots", label: "Shots", hint: "Browse history" },
    { id: "upload", label: "Upload", hint: "Classify a new image" },
    { id: "stats", label: "Stats", hint: "Aggregate analytics" },
  ];
  // "sho" should pick Shots (startsWith) first.
  const r1 = rankNav("sho", nav, 8);
  assert.equal(r1[0].id, "shots");

  // "image" appears only in upload's hint.
  const r2 = rankNav("image", nav, 8);
  assert.equal(r2.length, 1);
  assert.equal(r2[0].id, "upload");

  // No match returns empty.
  const r3 = rankNav("zzzzz", nav, 8);
  assert.equal(r3.length, 0);

  // Limit honored.
  const nav2 = Array.from({ length: 20 }, (_, i) => ({
    id: `n${i}`,
    label: `Page${i}`,
    hint: "x",
  }));
  const r4 = rankNav("", nav2, 5);
  assert.equal(r4.length, 5);
});
