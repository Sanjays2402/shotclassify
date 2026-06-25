// Pure tests for the pinned-shots quick-bar helpers. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  pinnedQuickItems,
  pinnedCount,
  pinnedOverflow,
  PINNED_BAR_DEFAULT_CAP,
  type PinnableShot,
} from "./pinned-bar.ts";

function shot(over: Partial<PinnableShot> & { id: string }): PinnableShot {
  return {
    filename: `${over.id}.png`,
    primary_category: "receipt",
    confidence: 0.9,
    created_at: "2026-06-01T00:00:00Z",
    pinned: false,
    ...over,
  };
}

test("pinnedQuickItems: empty / null / undefined yields []", () => {
  assert.deepEqual(pinnedQuickItems([]), []);
  assert.deepEqual(pinnedQuickItems(null), []);
  assert.deepEqual(pinnedQuickItems(undefined), []);
});

test("pinnedQuickItems: keeps only pinned rows", () => {
  const items = pinnedQuickItems([
    shot({ id: "a", pinned: true }),
    shot({ id: "b", pinned: false }),
    shot({ id: "c", pinned: true }),
  ]);
  assert.deepEqual(items.map((i) => i.id).sort(), ["a", "c"]);
});

test("pinnedQuickItems: newest first", () => {
  const items = pinnedQuickItems([
    shot({ id: "old", pinned: true, created_at: "2026-01-01T00:00:00Z" }),
    shot({ id: "new", pinned: true, created_at: "2026-06-01T00:00:00Z" }),
    shot({ id: "mid", pinned: true, created_at: "2026-03-01T00:00:00Z" }),
  ]);
  assert.deepEqual(items.map((i) => i.id), ["new", "mid", "old"]);
});

test("pinnedQuickItems: de-duplicates by id (first wins)", () => {
  const items = pinnedQuickItems([
    shot({ id: "dup", pinned: true }),
    shot({ id: "dup", pinned: true }),
    shot({ id: "x", pinned: true }),
  ]);
  assert.equal(items.length, 2);
});

test("pinnedQuickItems: name prefers label, then filename, then id", () => {
  const items = pinnedQuickItems([
    shot({ id: "a", pinned: true, label: "  Coffee run  ", filename: "f.png" }),
    shot({ id: "b", pinned: true, label: "   ", filename: "bill.png" }),
    shot({ id: "c", pinned: true, label: null, filename: "" }),
  ]);
  const byId = Object.fromEntries(items.map((i) => [i.id, i.name]));
  assert.equal(byId["a"], "Coffee run"); // trimmed label
  assert.equal(byId["b"], "bill.png"); // blank label -> filename
  assert.equal(byId["c"], "c"); // no label/filename -> id
});

test("pinnedQuickItems: caps the list, default cap is 12", () => {
  const many = Array.from({ length: 20 }, (_, i) =>
    shot({ id: `p${i}`, pinned: true, created_at: `2026-06-${(i % 28) + 1}T00:00:00Z` }),
  );
  assert.equal(pinnedQuickItems(many).length, PINNED_BAR_DEFAULT_CAP);
  assert.equal(pinnedQuickItems(many, 5).length, 5);
  // A nonsense cap falls back to the default.
  assert.equal(pinnedQuickItems(many, 0).length, PINNED_BAR_DEFAULT_CAP);
  assert.equal(pinnedQuickItems(many, -3).length, PINNED_BAR_DEFAULT_CAP);
});

test("pinnedQuickItems: tolerates a bad created_at (sorts last, no throw)", () => {
  const items = pinnedQuickItems([
    shot({ id: "good", pinned: true, created_at: "2026-06-01T00:00:00Z" }),
    shot({ id: "bad", pinned: true, created_at: "not-a-date" }),
  ]);
  assert.deepEqual(items.map((i) => i.id), ["good", "bad"]);
});

test("pinnedCount: counts unique pinned rows", () => {
  assert.equal(
    pinnedCount([
      shot({ id: "a", pinned: true }),
      shot({ id: "a", pinned: true }), // dup
      shot({ id: "b", pinned: true }),
      shot({ id: "c", pinned: false }),
    ]),
    2,
  );
  assert.equal(pinnedCount(null), 0);
});

test("pinnedOverflow: how many pinned are hidden beyond the cap", () => {
  const many = Array.from({ length: 15 }, (_, i) => shot({ id: `p${i}`, pinned: true }));
  assert.equal(pinnedOverflow(many), 3); // 15 - 12
  assert.equal(pinnedOverflow(many, 5), 10);
  assert.equal(pinnedOverflow(many, 100), 0); // never negative
});
