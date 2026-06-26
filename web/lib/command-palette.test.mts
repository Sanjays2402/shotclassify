import { test } from "node:test";
import assert from "node:assert/strict";
import { fuzzyScore, rankNav, digitJumpIndex, paletteRestingHint, PALETTE_RESTING_HINT, shotsScopeHints, shortLabelForHint } from "./command-palette";

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

// --- F50: resting-palette discoverability hint ---------------------------

test("paletteRestingHint: shown only when resting AND no recents", () => {
  assert.equal(paletteRestingHint(true, 0), PALETTE_RESTING_HINT);
});

test("paletteRestingHint: hidden the moment the user types (not resting)", () => {
  assert.equal(paletteRestingHint(false, 0), null);
  assert.equal(paletteRestingHint(false, 3), null);
});

test("paletteRestingHint: hidden once the recents ring has entries", () => {
  assert.equal(paletteRestingHint(true, 1), null);
  assert.equal(paletteRestingHint(true, 6), null);
});

test("paletteRestingHint: a non-finite count is treated as empty (still shows)", () => {
  assert.equal(paletteRestingHint(true, NaN), PALETTE_RESTING_HINT);
});

// --- shots-scope footer legend (F70) -------------------------------------

const FAKE_SHORTCUTS = [
  { id: "open-palette", scope: "global", combo: { keys: ["Cmd", "K"] }, label: "Open palette" },
  { id: "cycle-view", scope: "shots", combo: { keys: ["V"] }, label: "Cycle list view (Table / Grid / Compact)" },
  { id: "cycle-grid-density", scope: "shots", combo: { keys: ["D"] }, label: "Cycle grid density (Roomy / Default / Dense)" },
  { id: "detail-prev", scope: "detail", combo: { keys: ["["] }, label: "Newer shot" },
  { id: "no-keys", scope: "shots", combo: { keys: [] }, label: "Bogus, no keys" },
];

test("shotsScopeHints: returns only shots-scope shortcuts that have keys", () => {
  const hints = shotsScopeHints(FAKE_SHORTCUTS);
  assert.deepEqual(
    hints.map((h) => h.id),
    ["cycle-view", "cycle-grid-density"],
  );
  // Carries the rendered key glyph(s) + the full label.
  assert.deepEqual(hints[0].keys, ["V"]);
  assert.equal(hints[1].keys[0], "D");
});

test("shotsScopeHints: a non-array input is tolerated", () => {
  assert.deepEqual(shotsScopeHints(undefined as never), []);
  assert.deepEqual(shotsScopeHints(null as never), []);
});

test("shotsScopeHints: the real catalogue lights up v + d", async () => {
  const { SHORTCUTS } = await import("./shortcuts.ts");
  const ids = shotsScopeHints(SHORTCUTS).map((h) => h.id);
  assert.ok(ids.includes("cycle-view"), "view cycle should appear");
  assert.ok(ids.includes("cycle-grid-density"), "density cycle should appear");
  // Nothing from another scope leaks in.
  assert.ok(!ids.includes("open-palette"));
  assert.ok(!ids.includes("cycle-stats-window"));
});

test("shortLabelForHint: drops the parenthetical and the leading 'Cycle '", () => {
  assert.equal(
    shortLabelForHint("Cycle list view (Table / Grid / Compact)"),
    "list view",
  );
  assert.equal(
    shortLabelForHint("Cycle grid density (Roomy / Default / Dense)"),
    "grid density",
  );
});

test("shortLabelForHint: falls back to the trimmed label when nothing to strip", () => {
  assert.equal(shortLabelForHint("Pin shot"), "Pin shot");
  assert.equal(shortLabelForHint("  Spaced  "), "Spaced");
  assert.equal(shortLabelForHint(undefined as never), "");
});
