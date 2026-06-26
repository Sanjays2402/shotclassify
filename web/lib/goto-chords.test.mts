// Pure tests for the "go to" chord -> route mapping (F57). No DOM / router.
import test from "node:test";
import assert from "node:assert/strict";

import {
  GOTO_CHORDS,
  routeForChord,
  isGotoChord,
} from "./goto-chords.ts";
import { SHORTCUTS, createSequenceTracker, type KeyLike } from "./shortcuts.ts";

function ev(over: Partial<KeyLike>): KeyLike {
  return {
    key: "",
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    ...over,
  };
}

test("routeForChord: every catalogued chord resolves to its route", () => {
  assert.equal(routeForChord("g l"), "/");
  assert.equal(routeForChord("g h"), "/shots");
  assert.equal(routeForChord("g s"), "/stats");
  assert.equal(routeForChord("g u"), "/upload");
  assert.equal(routeForChord("g c"), "/calibration");
});

test("routeForChord: 'g t' (scroll-to-top) is NOT a section jump", () => {
  // g t is owned by HotKeys directly; this module must not claim it or the
  // chord would navigate instead of scrolling.
  assert.equal(routeForChord("g t"), null);
});

test("routeForChord: unknown / malformed sequences degrade to null", () => {
  assert.equal(routeForChord("g x"), null);
  assert.equal(routeForChord("s"), null);
  assert.equal(routeForChord(""), null);
  assert.equal(routeForChord("   "), null);
  assert.equal(routeForChord(null), null);
  assert.equal(routeForChord(undefined), null);
  assert.equal(routeForChord(123 as unknown as string), null);
});

test("routeForChord: normalises case and extra whitespace", () => {
  assert.equal(routeForChord("G S"), "/stats");
  assert.equal(routeForChord("  g   s  "), "/stats");
  assert.equal(routeForChord("g\tH"), "/shots");
});

test("isGotoChord: boolean mirror of routeForChord", () => {
  assert.equal(isGotoChord("g s"), true);
  assert.equal(isGotoChord("g t"), false);
  assert.equal(isGotoChord("nope"), false);
});

test("GOTO_CHORDS: stable shape -- unique seqs, two glyphs, leading G", () => {
  const seqs = new Set(GOTO_CHORDS.map((c) => c.seq));
  assert.equal(seqs.size, GOTO_CHORDS.length, "chord seqs must be unique");
  const routes = new Set(GOTO_CHORDS.map((c) => c.route));
  assert.equal(routes.size, GOTO_CHORDS.length, "routes must be unique");
  for (const c of GOTO_CHORDS) {
    assert.equal(c.keys.length, 2, `${c.seq} renders two glyphs`);
    assert.equal(c.keys[0], "G", `${c.seq} starts with G`);
    assert.match(c.seq, /^g [a-z]$/, `${c.seq} is "g <letter>"`);
    assert.ok(c.label.startsWith("Go to "), `${c.seq} label`);
  }
});

test("every goto chord is registered in the SHORTCUTS catalogue", () => {
  // The sequence tracker only recognises chords that appear in SHORTCUTS, so
  // a chord missing from the catalogue would silently never fire.
  const matches = new Set(SHORTCUTS.map((s) => s.combo.match));
  for (const c of GOTO_CHORDS) {
    assert.ok(matches.has(c.seq), `SHORTCUTS is missing ${c.seq}`);
  }
});

test("the shared sequence tracker fires goto chords end-to-end", () => {
  // Integration with the real tracker: G then S within the window emits the
  // sequence string that routeForChord maps to /stats. This guards the wiring
  // contract HotKeys relies on.
  const tr = createSequenceTracker(SHORTCUTS, 1000);
  assert.equal(tr.feed(ev({ key: "g" }), 0), null);
  const seq = tr.feed(ev({ key: "s" }), 120);
  assert.equal(seq, "g s");
  assert.equal(routeForChord(seq), "/stats");
});

test("a held modifier during a chord aborts it (no accidental nav)", () => {
  const tr = createSequenceTracker(SHORTCUTS, 1000);
  assert.equal(tr.feed(ev({ key: "g" }), 0), null);
  // Cmd-H (hide window) must not complete `g h`.
  assert.equal(tr.feed(ev({ key: "h", metaKey: true }), 80), null);
});
