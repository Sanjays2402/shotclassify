// Pure tests for the recently-viewed-shots MRU ring (F32). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  pushRecentShot,
  parseRecentShots,
  serializeRecentShots,
  clearRecentShots,
  RECENT_SHOTS_MAX,
  RECENT_SHOTS_STORAGE_KEY,
  type RecentShot,
} from "./recent-shots.ts";

function shot(id: string, viewedAt: number, over: Partial<RecentShot> = {}): RecentShot {
  return { id, label: id, viewedAt, ...over };
}

test("RECENT_SHOTS_STORAGE_KEY is stable", () => {
  assert.equal(RECENT_SHOTS_STORAGE_KEY, "shotclassify.recent.shots");
});

test("pushRecentShot: newest goes to the front", () => {
  let list: RecentShot[] = [];
  list = pushRecentShot(list, shot("a", 1));
  list = pushRecentShot(list, shot("b", 2));
  assert.deepEqual(
    list.map((s) => s.id),
    ["b", "a"],
  );
});

test("pushRecentShot: re-viewing an id moves it to the front, no dupe", () => {
  let list: RecentShot[] = [];
  list = pushRecentShot(list, shot("a", 1));
  list = pushRecentShot(list, shot("b", 2));
  list = pushRecentShot(list, shot("a", 3, { label: "Alpha refreshed" }));
  assert.deepEqual(
    list.map((s) => s.id),
    ["a", "b"],
  );
  // Metadata refreshed to the latest visit.
  assert.equal(list[0].label, "Alpha refreshed");
  assert.equal(list[0].viewedAt, 3);
});

test("pushRecentShot: caps at the max, dropping the oldest", () => {
  let list: RecentShot[] = [];
  for (let i = 0; i < RECENT_SHOTS_MAX + 3; i++) {
    list = pushRecentShot(list, shot(`s${i}`, i));
  }
  assert.equal(list.length, RECENT_SHOTS_MAX);
  // The three oldest (s0, s1, s2) fell off the tail.
  assert.equal(list[0].id, `s${RECENT_SHOTS_MAX + 2}`);
  assert.ok(!list.some((s) => s.id === "s0"));
});

test("pushRecentShot: a blank id is rejected, list unchanged", () => {
  const base = [shot("a", 1)];
  const after = pushRecentShot(base, shot("   ", 2));
  assert.deepEqual(
    after.map((s) => s.id),
    ["a"],
  );
});

test("pushRecentShot: empty label falls back to the id", () => {
  const list = pushRecentShot([], { id: "xyz", label: "  ", viewedAt: 1 });
  assert.equal(list[0].label, "xyz");
});

test("parseRecentShots: drops malformed entries and de-dupes by id", () => {
  const parsed = parseRecentShots([
    { id: "a", label: "A", viewedAt: 3 },
    null,
    42,
    { label: "no id", viewedAt: 9 },
    { id: "a", label: "dupe", viewedAt: 1 }, // duplicate id -> dropped
    { id: "b", label: "B", viewedAt: 5 },
  ]);
  assert.deepEqual(
    parsed.map((s) => s.id),
    ["b", "a"], // sorted newest-first by viewedAt
  );
});

test("parseRecentShots: non-array input yields an empty list", () => {
  assert.deepEqual(parseRecentShots(null), []);
  assert.deepEqual(parseRecentShots("nope"), []);
  assert.deepEqual(parseRecentShots({ id: "a" }), []);
});

test("parseRecentShots: honours the cap", () => {
  const raw = Array.from({ length: 20 }, (_, i) => ({
    id: `s${i}`,
    label: `S${i}`,
    viewedAt: i,
  }));
  assert.equal(parseRecentShots(raw).length, RECENT_SHOTS_MAX);
});

test("serialize -> parse round-trips a clean list", () => {
  const list = [shot("a", 2, { category: "receipt" }), shot("b", 1)];
  const round = parseRecentShots(JSON.parse(serializeRecentShots(list)));
  assert.deepEqual(
    round.map((s) => s.id),
    ["a", "b"],
  );
  assert.equal(round[0].category, "receipt");
});

// --- F42: clearRecentShots ------------------------------------------------

test("clearRecentShots: no window (SSR) returns false, never throws", () => {
  // In the node:test runtime there's no `window` global by default.
  assert.equal(typeof (globalThis as { window?: unknown }).window, "undefined");
  assert.equal(clearRecentShots(), false);
});

test("clearRecentShots: removes the ring key and reports true", () => {
  const store = new Map<string, string>([
    [RECENT_SHOTS_STORAGE_KEY, serializeRecentShots([shot("a", 1)])],
    ["keep-me", "untouched"],
  ]);
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  };
  try {
    assert.equal(clearRecentShots(), true);
    assert.equal(store.has(RECENT_SHOTS_STORAGE_KEY), false);
    // Only the ring key is touched; unrelated keys survive.
    assert.equal(store.get("keep-me"), "untouched");
  } finally {
    delete g.window;
  }
});

test("clearRecentShots: a throwing storage is swallowed -> false", () => {
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      removeItem: () => {
        throw new Error("blocked");
      },
    },
  };
  try {
    assert.equal(clearRecentShots(), false);
  } finally {
    delete g.window;
  }
});
