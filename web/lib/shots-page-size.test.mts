// Pure tests for the /shots page-size persistence helper (F51). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseShotsPageSize,
  serializeShotsPageSize,
  labelForShotsPageSize,
  readShotsPageSize,
  writeShotsPageSize,
  SHOTS_PAGE_SIZES,
  SHOTS_PAGE_SIZE_DEFAULT,
  SHOTS_PAGE_SIZE_STORAGE_KEY,
} from "./shots-page-size.ts";

test("SHOTS_PAGE_SIZE constants are stable", () => {
  assert.equal(SHOTS_PAGE_SIZE_STORAGE_KEY, "shotclassify.shots.pagesize");
  assert.equal(SHOTS_PAGE_SIZE_DEFAULT, 50);
  assert.deepEqual(SHOTS_PAGE_SIZES, [25, 50, 100, 200]);
});

test("parseShotsPageSize: known numbers pass through", () => {
  assert.equal(parseShotsPageSize(25), 25);
  assert.equal(parseShotsPageSize(50), 50);
  assert.equal(parseShotsPageSize(100), 100);
  assert.equal(parseShotsPageSize(200), 200);
});

test("parseShotsPageSize: known numeric strings pass through", () => {
  assert.equal(parseShotsPageSize("25"), 25);
  assert.equal(parseShotsPageSize("  100  "), 100);
  assert.equal(parseShotsPageSize("200"), 200);
});

test("parseShotsPageSize: unknown / junk values fall back to the default", () => {
  for (const v of [0, 1, 99, 75, 500, "nope", "", "  ", "50/page", null, undefined, NaN]) {
    assert.equal(
      parseShotsPageSize(v as never),
      SHOTS_PAGE_SIZE_DEFAULT,
      JSON.stringify(v),
    );
  }
});

test("serialize -> parse round-trips every known size", () => {
  for (const n of SHOTS_PAGE_SIZES) {
    assert.equal(parseShotsPageSize(serializeShotsPageSize(n)), n);
  }
});

test("labelForShotsPageSize: human label per size", () => {
  assert.equal(labelForShotsPageSize(25), "25 / page");
  assert.equal(labelForShotsPageSize(200), "200 / page");
});

test("readShotsPageSize: SSR (no window) returns the default", () => {
  assert.equal(typeof (globalThis as { window?: unknown }).window, "undefined");
  assert.equal(readShotsPageSize(), SHOTS_PAGE_SIZE_DEFAULT);
});

test("read/writeShotsPageSize: round-trip through a stubbed localStorage", () => {
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
    assert.equal(readShotsPageSize(), SHOTS_PAGE_SIZE_DEFAULT);
    writeShotsPageSize(200);
    assert.equal(store.get(SHOTS_PAGE_SIZE_STORAGE_KEY), "200");
    assert.equal(readShotsPageSize(), 200);
    // A corrupt stored value is coerced back to the default on read.
    store.set(SHOTS_PAGE_SIZE_STORAGE_KEY, "bogus");
    assert.equal(readShotsPageSize(), SHOTS_PAGE_SIZE_DEFAULT);
  } finally {
    delete g.window;
  }
});

test("writeShotsPageSize: a throwing storage is swallowed", () => {
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      setItem: () => {
        throw new Error("quota");
      },
    },
  };
  try {
    assert.doesNotThrow(() => writeShotsPageSize(100));
  } finally {
    delete g.window;
  }
});
