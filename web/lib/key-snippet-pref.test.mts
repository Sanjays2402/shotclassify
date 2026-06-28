// Pure tests for the /keys snippet-language persistence (F135). No DOM:
// these cover the parse/serialize contract via a fake localStorage so the
// browser wrappers are exercised without jsdom. Mirrors lib/recent-shots
// coverage style (typed globalThis.window shim).
import test from "node:test";
import assert from "node:assert/strict";

import {
  KEY_SNIPPET_LANG_STORAGE_KEY,
  KEY_SNIPPET_LANG_DEFAULT,
  serializeSnippetLang,
  readSnippetLang,
  writeSnippetLang,
} from "./key-snippet-pref.ts";

// Minimal localStorage shim so the no-throw wrappers have something to talk to.
function seedWindow(seed: Record<string, string>) {
  const store = new Map<string, string>(Object.entries(seed));
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  };
  return store;
}
function clearWindow() {
  delete (globalThis as { window?: unknown }).window;
}

test("default + storage key are stable", () => {
  assert.equal(KEY_SNIPPET_LANG_DEFAULT, "curl");
  assert.equal(KEY_SNIPPET_LANG_STORAGE_KEY, "shotclassify.keys.snippetLang");
});

test("serializeSnippetLang round-trips known languages", () => {
  assert.equal(serializeSnippetLang("curl"), "curl");
  assert.equal(serializeSnippetLang("python"), "python");
  assert.equal(serializeSnippetLang("javascript"), "javascript");
});

test("serializeSnippetLang sanitises a bad value to the default", () => {
  assert.equal(serializeSnippetLang("ruby" as never), "curl");
  assert.equal(serializeSnippetLang(null as never), "curl");
});

test("readSnippetLang returns default on SSR (no window)", () => {
  clearWindow();
  assert.equal(readSnippetLang(), "curl");
});

test("readSnippetLang returns default when nothing stored", () => {
  seedWindow({});
  assert.equal(readSnippetLang(), "curl");
  clearWindow();
});

test("readSnippetLang reads a persisted language", () => {
  seedWindow({ "shotclassify.keys.snippetLang": "python" });
  assert.equal(readSnippetLang(), "python");
  clearWindow();
});

test("readSnippetLang coerces a corrupt value to the default", () => {
  seedWindow({ "shotclassify.keys.snippetLang": "cobol" });
  assert.equal(readSnippetLang(), "curl");
  clearWindow();
});

test("writeSnippetLang then readSnippetLang is symmetric", () => {
  seedWindow({});
  writeSnippetLang("javascript");
  assert.equal(readSnippetLang(), "javascript");
  clearWindow();
});

test("writeSnippetLang is no-throw on SSR", () => {
  clearWindow();
  assert.doesNotThrow(() => writeSnippetLang("python"));
});

test("read/write swallow a throwing storage", () => {
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    },
  };
  try {
    assert.equal(readSnippetLang(), "curl");
    assert.doesNotThrow(() => writeSnippetLang("python"));
  } finally {
    clearWindow();
  }
});
