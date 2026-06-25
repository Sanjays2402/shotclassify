// Pure tests for the changelog helpers. No DOM, no localStorage.
import test from "node:test";
import assert from "node:assert/strict";

import {
  CHANGELOG,
  currentVersion,
  latestEntry,
  hasUnseen,
  unseenCount,
  formatEntryDate,
  type ChangelogEntry,
} from "./changelog.ts";

const SAMPLE: ChangelogEntry[] = [
  { version: "0.5", date: "2026-06-25", title: "newest", highlights: ["a"] },
  { version: "0.4", date: "2026-06-24", title: "mid", highlights: ["b"] },
  { version: "0.3", date: "2026-06-23", title: "old", highlights: ["c"] },
];

test("the real CHANGELOG is well-formed and newest-first", () => {
  assert.ok(CHANGELOG.length >= 1);
  for (const e of CHANGELOG) {
    assert.ok(e.version.length > 0);
    assert.match(e.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(e.title.length > 0);
    assert.ok(Array.isArray(e.highlights) && e.highlights.length > 0);
  }
  // Dates should be non-increasing down the list (newest at the top).
  for (let i = 1; i < CHANGELOG.length; i++) {
    assert.ok(
      CHANGELOG[i - 1].date >= CHANGELOG[i].date,
      `entry ${i} is out of order`,
    );
  }
});

test("currentVersion / latestEntry read the top of the list", () => {
  assert.equal(currentVersion(SAMPLE), "0.5");
  assert.equal(latestEntry(SAMPLE)?.title, "newest");
  assert.equal(currentVersion([]), "0.0");
  assert.equal(latestEntry([]), undefined);
});

test("hasUnseen: no pointer or stale pointer means unseen", () => {
  assert.equal(hasUnseen(null, SAMPLE), true);
  assert.equal(hasUnseen("", SAMPLE), true);
  assert.equal(hasUnseen("0.4", SAMPLE), true); // behind current
  assert.equal(hasUnseen("0.5", SAMPLE), false); // caught up
});

test("hasUnseen: also true on rollback (pointer ahead of current)", () => {
  assert.equal(hasUnseen("0.9", SAMPLE), true);
});

test("hasUnseen: empty log is never unseen", () => {
  assert.equal(hasUnseen(null, []), false);
  assert.equal(hasUnseen("1.0", []), false);
});

test("unseenCount: counts entries newer than the stored pointer", () => {
  assert.equal(unseenCount(null, SAMPLE), 3); // never seen anything
  assert.equal(unseenCount("0.5", SAMPLE), 0); // current
  assert.equal(unseenCount("0.4", SAMPLE), 1); // one newer (0.5)
  assert.equal(unseenCount("0.3", SAMPLE), 2); // two newer (0.5, 0.4)
});

test("unseenCount: unknown pointer counts everything as new", () => {
  assert.equal(unseenCount("9.9", SAMPLE), 3);
});

test("unseenCount: empty log is zero", () => {
  assert.equal(unseenCount(null, []), 0);
});

test("formatEntryDate: renders a locale date, falls back on garbage", () => {
  const s = formatEntryDate("2026-06-25");
  assert.match(s, /2026/);
  // Garbage in -> same string back (no throw).
  assert.equal(formatEntryDate("not-a-date"), "not-a-date");
});
