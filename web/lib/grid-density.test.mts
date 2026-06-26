// Pure tests for the /shots grid column-density helper (F29). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseGridDensity,
  serializeGridDensity,
  gridColumnsClass,
  labelForGridDensity,
  readGridDensity,
  writeGridDensity,
  GRID_DENSITIES,
  GRID_DENSITY_DEFAULT,
  GRID_DENSITY_STORAGE_KEY,
} from "./grid-density.ts";

test("GRID density constants are stable", () => {
  assert.equal(GRID_DENSITY_STORAGE_KEY, "shotclassify.shots.grid.density");
  assert.equal(GRID_DENSITY_DEFAULT, "default");
  assert.deepEqual(GRID_DENSITIES, ["roomy", "default", "dense"]);
});

test("parseGridDensity: known values pass through (case / space tolerant)", () => {
  assert.equal(parseGridDensity("roomy"), "roomy");
  assert.equal(parseGridDensity("default"), "default");
  assert.equal(parseGridDensity("dense"), "dense");
  assert.equal(parseGridDensity("  DENSE  "), "dense");
  assert.equal(parseGridDensity("Roomy"), "roomy");
});

test("parseGridDensity: junk falls back to the default", () => {
  for (const v of ["", "  ", "wide", "2", "cols-3", null, undefined]) {
    assert.equal(parseGridDensity(v as never), GRID_DENSITY_DEFAULT, JSON.stringify(v));
  }
});

test("serialize -> parse round-trips every density", () => {
  for (const d of GRID_DENSITIES) {
    assert.equal(parseGridDensity(serializeGridDensity(d)), d);
  }
});

test("gridColumnsClass: returns static, non-empty Tailwind class strings", () => {
  // The strings MUST be literal (no interpolation) so Tailwind emits them.
  assert.equal(
    gridColumnsClass("default"),
    "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
  );
  assert.equal(
    gridColumnsClass("roomy"),
    "grid-cols-1 sm:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3",
  );
  assert.equal(
    gridColumnsClass("dense"),
    "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6",
  );
});

test("gridColumnsClass: every density climbs to a wider or equal max", () => {
  // Sanity: roomy <= default <= dense at the xl breakpoint.
  const xlCols = (cls: string) => {
    const m = cls.match(/xl:grid-cols-(\d+)/);
    return m ? Number(m[1]) : 0;
  };
  assert.ok(xlCols(gridColumnsClass("roomy")) < xlCols(gridColumnsClass("default")));
  assert.ok(xlCols(gridColumnsClass("default")) < xlCols(gridColumnsClass("dense")));
});

test("gridColumnsClass: an unknown density coerces through the default", () => {
  assert.equal(
    gridColumnsClass("bogus" as never),
    gridColumnsClass(GRID_DENSITY_DEFAULT),
  );
});

test("labelForGridDensity: human labels", () => {
  assert.equal(labelForGridDensity("roomy"), "Roomy");
  assert.equal(labelForGridDensity("default"), "Default");
  assert.equal(labelForGridDensity("dense"), "Dense");
});

test("readGridDensity: SSR (no window) returns the default", () => {
  assert.equal(typeof (globalThis as { window?: unknown }).window, "undefined");
  assert.equal(readGridDensity(), GRID_DENSITY_DEFAULT);
});

test("read/writeGridDensity: round-trip through a stubbed localStorage", () => {
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
    assert.equal(readGridDensity(), GRID_DENSITY_DEFAULT);
    writeGridDensity("dense");
    assert.equal(store.get(GRID_DENSITY_STORAGE_KEY), "dense");
    assert.equal(readGridDensity(), "dense");
    store.set(GRID_DENSITY_STORAGE_KEY, "garbage");
    assert.equal(readGridDensity(), GRID_DENSITY_DEFAULT);
  } finally {
    delete g.window;
  }
});

test("writeGridDensity: a throwing storage is swallowed", () => {
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      setItem: () => {
        throw new Error("quota");
      },
    },
  };
  try {
    assert.doesNotThrow(() => writeGridDensity("roomy"));
  } finally {
    delete g.window;
  }
});
