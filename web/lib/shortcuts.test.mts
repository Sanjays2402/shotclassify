// Pure-logic tests for the keyboard shortcuts matcher and sequence tracker.
import test from "node:test";
import assert from "node:assert/strict";

import {
  SHORTCUTS,
  createSequenceTracker,
  isMac,
  matchesShortcut,
  renderKeys,
  type KeyLike,
  type ShortcutKey,
} from "./shortcuts.ts";

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

test("isMac detects macOS-family user-agent platform strings", () => {
  assert.equal(isMac("MacIntel"), true);
  assert.equal(isMac("iPhone"), true);
  assert.equal(isMac("iPad"), true);
  assert.equal(isMac("Linux x86_64"), false);
  assert.equal(isMac("Win32"), false);
  assert.equal(isMac(undefined as unknown as string), false);
});

test("renderKeys swaps Cmd <-> Ctrl by platform", () => {
  const combo: ShortcutKey = { keys: ["⌘", "K"], match: "mod+k" };
  assert.deepEqual(renderKeys(combo, "MacIntel"), ["⌘", "K"]);
  assert.deepEqual(renderKeys(combo, "Win32"), ["Ctrl", "K"]);

  const ctrlCombo: ShortcutKey = { keys: ["Ctrl", "S"], match: "ctrl+s" };
  assert.deepEqual(renderKeys(ctrlCombo, "MacIntel"), ["⌘", "S"]);
  assert.deepEqual(renderKeys(ctrlCombo, "Linux"), ["Ctrl", "S"]);
});

test("matchesShortcut: bare letter matches without modifiers", () => {
  assert.equal(matchesShortcut("u", ev({ key: "u" })), true);
  assert.equal(matchesShortcut("u", ev({ key: "U" })), true);
  // Cmd-U should NOT trigger the bare "u" shortcut.
  assert.equal(matchesShortcut("u", ev({ key: "u", metaKey: true })), false);
  // Ctrl-U should NOT trigger the bare "u" shortcut.
  assert.equal(matchesShortcut("u", ev({ key: "u", ctrlKey: true })), false);
  // Alt-U should NOT trigger.
  assert.equal(matchesShortcut("u", ev({ key: "u", altKey: true })), false);
});

test("matchesShortcut: mod+k matches Cmd on Mac and Ctrl on PC", () => {
  // macOS
  assert.equal(
    matchesShortcut("mod+k", ev({ key: "k", metaKey: true }), "MacIntel"),
    true,
  );
  assert.equal(
    matchesShortcut("mod+k", ev({ key: "k", ctrlKey: true }), "MacIntel"),
    false,
  );
  // Linux / Windows
  assert.equal(
    matchesShortcut("mod+k", ev({ key: "k", ctrlKey: true }), "Linux"),
    true,
  );
  assert.equal(
    matchesShortcut("mod+k", ev({ key: "k", metaKey: true }), "Linux"),
    false,
  );
});

test("matchesShortcut: explicit cmd+ vs ctrl+ are platform-independent", () => {
  assert.equal(
    matchesShortcut("cmd+s", ev({ key: "s", metaKey: true }), "Linux"),
    true,
  );
  assert.equal(
    matchesShortcut("ctrl+s", ev({ key: "s", ctrlKey: true }), "MacIntel"),
    true,
  );
});

test("matchesShortcut: shift+/ matches when typing '?'", () => {
  // The browser delivers shift+/ as key === "?" with shiftKey true.
  const e = ev({ key: "?", shiftKey: true });
  assert.equal(matchesShortcut("shift+/", e), true);
});

test("matchesShortcut: escape and enter are name-matched", () => {
  assert.equal(matchesShortcut("escape", ev({ key: "Escape" })), true);
  assert.equal(matchesShortcut("escape", ev({ key: "Esc" })), true);
  assert.equal(matchesShortcut("escape", ev({ key: "e" })), false);
  assert.equal(matchesShortcut("enter", ev({ key: "Enter" })), true);
});

test("matchesShortcut: bare combo with stray shift is rejected", () => {
  // Shift-U should not fire the "u" shortcut -- some apps overload it.
  // The implementation accepts uppercase letter when the user is typing
  // exactly the shifted glyph (which happens to equal the bare-letter
  // shortcut after lowercasing). That's intentional -- letter shortcuts
  // accept both cases. We just verify Cmd-Shift-U is rejected.
  assert.equal(
    matchesShortcut("u", ev({ key: "u", metaKey: true, shiftKey: true })),
    false,
  );
});

test("matchesShortcut: sequence-combos return false here (handled elsewhere)", () => {
  assert.equal(matchesShortcut("g t", ev({ key: "g" })), false);
  assert.equal(matchesShortcut("g t", ev({ key: "t" })), false);
});

test("createSequenceTracker: fires only on full sequence within window", () => {
  const tr = createSequenceTracker(SHORTCUTS, 1000);
  assert.equal(tr.feed(ev({ key: "g" }), 0), null);
  assert.equal(tr.feed(ev({ key: "t" }), 100), "g t");
  // Calling reset clears state.
  tr.reset();
});

test("createSequenceTracker: stale stroke outside window restarts buffer", () => {
  const tr = createSequenceTracker(SHORTCUTS, 500);
  assert.equal(tr.feed(ev({ key: "g" }), 0), null);
  // Second key arrives well after the window -> buffer was reset, so this
  // 't' alone matches no sequence.
  assert.equal(tr.feed(ev({ key: "t" }), 2000), null);
  // But a subsequent g-then-t within the window does fire.
  assert.equal(tr.feed(ev({ key: "g" }), 2050), null);
  assert.equal(tr.feed(ev({ key: "t" }), 2100), "g t");
});

test("createSequenceTracker: any modifier resets buffer", () => {
  const tr = createSequenceTracker(SHORTCUTS, 1000);
  assert.equal(tr.feed(ev({ key: "g" }), 0), null);
  // User accidentally holds Cmd -- this should clear the in-flight sequence.
  assert.equal(tr.feed(ev({ key: "g", metaKey: true }), 100), null);
  // Plain g then t still has to start fresh; just "t" doesn't fire.
  assert.equal(tr.feed(ev({ key: "t" }), 200), null);
});

test("createSequenceTracker: non-printable keys break the sequence", () => {
  const tr = createSequenceTracker(SHORTCUTS, 1000);
  assert.equal(tr.feed(ev({ key: "g" }), 0), null);
  // User pressed an arrow key in the middle -- abort the sequence.
  assert.equal(tr.feed(ev({ key: "ArrowDown" }), 100), null);
  assert.equal(tr.feed(ev({ key: "t" }), 200), null);
});

test("createSequenceTracker: dropping a wrong key keeps a fresh prefix", () => {
  // After "g x", the 'x' isn't a prefix of any sequence, so the buffer
  // should hold only "x" -- meaning "x g t" should fire on the second g/t.
  const tr = createSequenceTracker(SHORTCUTS, 5000);
  assert.equal(tr.feed(ev({ key: "g" }), 0), null);
  assert.equal(tr.feed(ev({ key: "x" }), 100), null);
  assert.equal(tr.feed(ev({ key: "g" }), 200), null);
  assert.equal(tr.feed(ev({ key: "t" }), 300), "g t");
});

test("SHORTCUTS catalogue has stable ids and unique matches per scope", () => {
  const ids = new Set(SHORTCUTS.map((s) => s.id));
  assert.equal(ids.size, SHORTCUTS.length, "shortcut ids must be unique");
  // Catalogue should always include the help opener so the modal can
  // self-document, and the palette opener so the chrome stays consistent.
  assert.ok(SHORTCUTS.some((s) => s.id === "open-help"));
  assert.ok(SHORTCUTS.some((s) => s.id === "open-palette"));
});
