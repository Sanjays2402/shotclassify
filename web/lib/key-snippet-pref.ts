// Persistence for the /keys snippet-language toggle (F135). F134 gave the
// page a curl / Python / JavaScript toggle, but it always reopened on curl.
// A Python shop returning to /keys should land on Python. This mirrors
// lib/stats-window.ts: a tiny, DOM-free parse/serialize pair plus no-throw
// browser wrappers, so a return visit reopens on the language you last used.
//
// The choice is identified by the SnippetLang value the page already feeds to
// buildSnippet, so there's no second source of truth to keep in sync --
// parseSnippetLang (lib/key-snippet) is the validator; this module only owns
// the storage key + default + read/write plumbing.

import { parseSnippetLang, type SnippetLang } from "./key-snippet";

export const KEY_SNIPPET_LANG_STORAGE_KEY = "shotclassify.keys.snippetLang";

// The default the page opens on the very first visit (no stored value) --
// matches buildSnippet's own default so behaviour is unchanged for newcomers.
export const KEY_SNIPPET_LANG_DEFAULT: SnippetLang = "curl";

// Serialize a language to the string localStorage stores. Symmetric with the
// read path (parseSnippetLang on the way back). A non-string / unknown value
// degrades to the default so a corrupt write can never round-trip a bad value.
export function serializeSnippetLang(lang: SnippetLang): string {
  return parseSnippetLang(lang);
}

// --- Browser wrappers (no-throw) -----------------------------------------

// Read the persisted language. Returns the default on SSR / blocked storage /
// a corrupt value. Safe to call from a mount effect.
export function readSnippetLang(): SnippetLang {
  if (typeof window === "undefined") return KEY_SNIPPET_LANG_DEFAULT;
  try {
    const raw = window.localStorage.getItem(KEY_SNIPPET_LANG_STORAGE_KEY);
    return raw === null ? KEY_SNIPPET_LANG_DEFAULT : parseSnippetLang(raw);
  } catch {
    return KEY_SNIPPET_LANG_DEFAULT;
  }
}

// Persist the selected language. No-throw: swallows quota / privacy-mode
// errors so a write failure never breaks the toggle.
export function writeSnippetLang(lang: SnippetLang): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      KEY_SNIPPET_LANG_STORAGE_KEY,
      serializeSnippetLang(lang),
    );
  } catch {
    // Ignore -- the in-memory selection still works for this session.
  }
}
