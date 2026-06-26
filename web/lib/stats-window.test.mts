// Pure tests for the /stats time-window persistence helper (F44). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseStatsWindow,
  serializeStatsWindow,
  labelForStatsWindow,
  readStatsWindow,
  writeStatsWindow,
  STATS_WINDOWS,
  STATS_WINDOW_DEFAULT,
  STATS_WINDOW_STORAGE_KEY,
} from "./stats-window.ts";

test("STATS constants are stable", () => {
  assert.equal(STATS_WINDOW_STORAGE_KEY, "shotclassify.stats.window");
  assert.equal(STATS_WINDOW_DEFAULT, 24);
  assert.deepEqual(STATS_WINDOWS, [24, 168, 720]);
});

test("parseStatsWindow: known numbers pass through", () => {
  assert.equal(parseStatsWindow(24), 24);
  assert.equal(parseStatsWindow(168), 168);
  assert.equal(parseStatsWindow(720), 720);
});

test("parseStatsWindow: known numeric strings pass through", () => {
  assert.equal(parseStatsWindow("24"), 24);
  assert.equal(parseStatsWindow("  168  "), 168);
  assert.equal(parseStatsWindow("720"), 720);
});

test("parseStatsWindow: unknown / junk values fall back to the default", () => {
  for (const v of [0, 1, 99, 48, "nope", "", "  ", "12h", null, undefined, NaN]) {
    assert.equal(parseStatsWindow(v as never), STATS_WINDOW_DEFAULT, JSON.stringify(v));
  }
});

test("serialize -> parse round-trips every known window", () => {
  for (const w of STATS_WINDOWS) {
    assert.equal(parseStatsWindow(serializeStatsWindow(w)), w);
  }
});

test("labelForStatsWindow: human labels per window", () => {
  assert.equal(labelForStatsWindow(24), "24h");
  assert.equal(labelForStatsWindow(168), "7d");
  assert.equal(labelForStatsWindow(720), "30d");
});

test("readStatsWindow: SSR (no window) returns the default", () => {
  assert.equal(typeof (globalThis as { window?: unknown }).window, "undefined");
  assert.equal(readStatsWindow(), STATS_WINDOW_DEFAULT);
});

test("read/writeStatsWindow: round-trip through a stubbed localStorage", () => {
  const store = new Map<string, string>();
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  };
  try {
    // Nothing stored yet -> default.
    assert.equal(readStatsWindow(), STATS_WINDOW_DEFAULT);
    writeStatsWindow(168);
    assert.equal(store.get(STATS_WINDOW_STORAGE_KEY), "168");
    assert.equal(readStatsWindow(), 168);
    // A corrupt stored value is coerced back to the default on read.
    store.set(STATS_WINDOW_STORAGE_KEY, "bogus");
    assert.equal(readStatsWindow(), STATS_WINDOW_DEFAULT);
  } finally {
    delete g.window;
  }
});

test("writeStatsWindow: a throwing storage is swallowed", () => {
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      setItem: () => {
        throw new Error("quota");
      },
    },
  };
  try {
    assert.doesNotThrow(() => writeStatsWindow(720));
  } finally {
    delete g.window;
  }
});
