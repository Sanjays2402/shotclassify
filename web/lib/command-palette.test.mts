import { test } from "node:test";
import assert from "node:assert/strict";
import { fuzzyScore, rankNav, digitJumpIndex } from "./command-palette";

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

// --- F45: digitJumpIndex (Cmd/Ctrl + 1-9 quick-jump) ----------------------

test("digitJumpIndex: 1-9 map to zero-based indices when in range", () => {
  assert.equal(digitJumpIndex("1", 9), 0);
  assert.equal(digitJumpIndex("2", 9), 1);
  assert.equal(digitJumpIndex("9", 9), 8);
});

test("digitJumpIndex: an index past the result count returns null", () => {
  // Only 3 results -> 1, 2, 3 valid; 4+ is null.
  assert.equal(digitJumpIndex("3", 3), 2);
  assert.equal(digitJumpIndex("4", 3), null);
  assert.equal(digitJumpIndex("9", 3), null);
});

test("digitJumpIndex: 0 is intentionally unbound", () => {
  assert.equal(digitJumpIndex("0", 9), null);
});

test("digitJumpIndex: non-digit / multi-char keys return null", () => {
  for (const k of ["a", "Enter", "", "12", "+", " "]) {
    assert.equal(digitJumpIndex(k, 9), null, JSON.stringify(k));
  }
});

test("digitJumpIndex: an empty / non-positive result set returns null", () => {
  assert.equal(digitJumpIndex("1", 0), null);
  assert.equal(digitJumpIndex("1", -3), null);
  assert.equal(digitJumpIndex("1", 1.5 as number), null);
});
