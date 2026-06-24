// Pure tests for the theme helpers. The component is wired separately;
// these guard the parse/resolve/cycle logic so we never paint the wrong
// palette and never break stored preferences across schema bumps.
import test from "node:test";
import assert from "node:assert/strict";

import {
  labelForMode,
  nextMode,
  parseStoredMode,
  resolveTheme,
  STORAGE_KEY,
  themeInitScript,
} from "./theme.ts";

test("STORAGE_KEY is stable", () => {
  // Hard-coded so a future rename can be reviewed deliberately.
  assert.equal(STORAGE_KEY, "shotclassify.theme");
});

test("parseStoredMode: accepts every known mode, case-insensitive", () => {
  assert.equal(parseStoredMode("light"), "light");
  assert.equal(parseStoredMode("DIM"), "dim");
  assert.equal(parseStoredMode("  System  "), "system");
});

test("parseStoredMode: falls back to system on anything unrecognised", () => {
  assert.equal(parseStoredMode(null), "system");
  assert.equal(parseStoredMode(undefined), "system");
  assert.equal(parseStoredMode(""), "system");
  assert.equal(parseStoredMode("garbage"), "system");
  // Defends against a 1.x value of "auto" if we ever rename keys.
  assert.equal(parseStoredMode("auto"), "system");
});

test("resolveTheme: explicit modes always win", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dim", false), "dim");
});

test("resolveTheme: system mode delegates to the OS", () => {
  assert.equal(resolveTheme("system", true), "dim");
  assert.equal(resolveTheme("system", false), "light");
});

test("nextMode: cycles light -> dim -> system -> light", () => {
  assert.equal(nextMode("light"), "dim");
  assert.equal(nextMode("dim"), "system");
  assert.equal(nextMode("system"), "light");
});

test("labelForMode: returns user-facing label per mode", () => {
  assert.equal(labelForMode("light"), "Light");
  assert.equal(labelForMode("dim"), "Dim");
  assert.equal(labelForMode("system"), "Auto");
});

test("themeInitScript: writes the correct attribute for stored 'dim'", () => {
  // Simulate the script's runtime by polyfilling the globals it touches.
  const fakeWindow: any = {
    matchMedia: () => ({ matches: false }),
  };
  const fakeStorage = new Map<string, string>([[STORAGE_KEY, "dim"]]);
  const fakeDoc: any = {
    documentElement: {
      attrs: {} as Record<string, string>,
      setAttribute(name: string, value: string) {
        this.attrs[name] = value;
      },
    },
  };
  // Tiny eval shim: wrap the script in a function with the polyfilled
  // locals visible by name.
  const fn = new Function(
    "window",
    "document",
    "localStorage",
    themeInitScript,
  );
  fn(
    fakeWindow,
    fakeDoc,
    {
      getItem: (k: string) => fakeStorage.get(k) ?? null,
    },
  );
  assert.equal(fakeDoc.documentElement.attrs["data-theme"], "dim");
  assert.equal(fakeDoc.documentElement.attrs["data-theme-mode"], "dim");
});

test("themeInitScript: 'system' mode flips to dim when OS prefers dark", () => {
  const fakeWindow: any = {
    matchMedia: () => ({ matches: true }),
  };
  const fakeStorage = new Map<string, string>([[STORAGE_KEY, "system"]]);
  const fakeDoc: any = {
    documentElement: {
      attrs: {} as Record<string, string>,
      setAttribute(name: string, value: string) {
        this.attrs[name] = value;
      },
    },
  };
  const fn = new Function(
    "window",
    "document",
    "localStorage",
    themeInitScript,
  );
  fn(fakeWindow, fakeDoc, {
    getItem: (k: string) => fakeStorage.get(k) ?? null,
  });
  assert.equal(fakeDoc.documentElement.attrs["data-theme"], "dim");
  assert.equal(fakeDoc.documentElement.attrs["data-theme-mode"], "system");
});

test("themeInitScript: missing localStorage entry defaults to system+light", () => {
  const fakeWindow: any = {
    matchMedia: () => ({ matches: false }),
  };
  const fakeStorage = new Map<string, string>();
  const fakeDoc: any = {
    documentElement: {
      attrs: {} as Record<string, string>,
      setAttribute(name: string, value: string) {
        this.attrs[name] = value;
      },
    },
  };
  const fn = new Function(
    "window",
    "document",
    "localStorage",
    themeInitScript,
  );
  fn(fakeWindow, fakeDoc, {
    getItem: (k: string) => fakeStorage.get(k) ?? null,
  });
  assert.equal(fakeDoc.documentElement.attrs["data-theme"], "light");
  assert.equal(fakeDoc.documentElement.attrs["data-theme-mode"], "system");
});

test("themeInitScript: malformed localStorage entry is treated as system", () => {
  const fakeWindow: any = {
    matchMedia: () => ({ matches: true }),
  };
  const fakeStorage = new Map<string, string>([[STORAGE_KEY, "rainbow"]]);
  const fakeDoc: any = {
    documentElement: {
      attrs: {} as Record<string, string>,
      setAttribute(name: string, value: string) {
        this.attrs[name] = value;
      },
    },
  };
  const fn = new Function(
    "window",
    "document",
    "localStorage",
    themeInitScript,
  );
  fn(fakeWindow, fakeDoc, {
    getItem: (k: string) => fakeStorage.get(k) ?? null,
  });
  // 'rainbow' -> coerced to 'system'; OS prefers dark -> dim.
  assert.equal(fakeDoc.documentElement.attrs["data-theme"], "dim");
  assert.equal(fakeDoc.documentElement.attrs["data-theme-mode"], "system");
});
