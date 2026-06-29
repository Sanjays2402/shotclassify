// Pure tests for the /digest category share-bar helper (F154). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  totalCategoryCount,
  categoryShares,
  categoryShareLabel,
} from "./category-share.ts";

const rows = [
  { category: "receipt", label: "Receipts", count: 60 },
  { category: "chat", label: "Chats", count: 30 },
  { category: "code", label: "Code", count: 10 },
];

test("totalCategoryCount: sums positive counts, ignores junk", () => {
  assert.equal(totalCategoryCount(rows), 100);
  assert.equal(totalCategoryCount([{ category: "a", label: "A", count: -5 }]), 0);
  assert.equal(totalCategoryCount([]), 0);
  assert.equal(totalCategoryCount(null), 0);
});

test("categoryShares: percent + width, preserves order", () => {
  const s = categoryShares(rows);
  assert.equal(s.length, 3);
  assert.equal(s[0].pct, 60);
  assert.equal(s[1].pct, 30);
  assert.equal(s[2].pct, 10);
  assert.equal(s[0].widthPct, "60.0%");
});

test("categoryShares: tiny class floors to a visible sliver", () => {
  const s = categoryShares([
    { category: "a", label: "A", count: 99 },
    { category: "b", label: "B", count: 1 },
  ]);
  assert.equal(s[1].pct, 1);
  assert.equal(s[1].widthPct, "4.0%");
});

test("categoryShares: zero total -> zero bars, no lie", () => {
  const s = categoryShares([{ category: "a", label: "A", count: 0 }]);
  assert.equal(s[0].share, 0);
  assert.equal(s[0].widthPct, "0%");
});

test("categoryShareLabel: percent or 'no shots'", () => {
  assert.equal(categoryShareLabel(categoryShares(rows)[0]), "60% of shots");
  assert.equal(categoryShareLabel({ category: "a", label: "A", count: 0, share: 0, pct: 0, widthPct: "0%" }), "no shots");
});
