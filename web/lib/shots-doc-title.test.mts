// Pure tests for the /shots document-title helper (F58). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { shotsDocTitle, SHOTS_TITLE_BASE } from "./shots-doc-title.ts";

test("SHOTS_TITLE_BASE is stable", () => {
  assert.equal(SHOTS_TITLE_BASE, "Shots");
});

test("shotsDocTitle: no filter -> just the base", () => {
  assert.equal(shotsDocTitle({}), "Shots");
  assert.equal(
    shotsDocTitle({ category: "", q: "", tag: "", minConfPct: 0, pinnedOnly: false }),
    "Shots",
  );
});

test("shotsDocTitle: a single filter leads the base", () => {
  assert.equal(shotsDocTitle({ category: "receipt" }), "Receipt · Shots");
  assert.equal(shotsDocTitle({ minConfPct: 90 }), ">=90% confidence · Shots");
  assert.equal(shotsDocTitle({ pinnedOnly: true }), "pinned only · Shots");
});

test("shotsDocTitle: multiple filters join with the mid-dot, base last", () => {
  assert.equal(
    shotsDocTitle({ category: "receipt", minConfPct: 90 }),
    "Receipt · >=90% confidence · Shots",
  );
  assert.equal(
    shotsDocTitle({ category: "chat_screenshot", tag: "urgent", pinnedOnly: true }),
    "Chat screenshot · #urgent · pinned only · Shots",
  );
});

test("shotsDocTitle: a custom base is honoured", () => {
  assert.equal(
    shotsDocTitle({ category: "receipt" }, "Shots · ShotClassify"),
    "Receipt · Shots · ShotClassify",
  );
});
