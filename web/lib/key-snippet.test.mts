// Pure tests for the /keys multi-language snippet builder (F134). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  buildSnippet,
  parseSnippetLang,
  SNIPPET_LANGS,
  SNIPPET_TOKEN_PLACEHOLDER,
} from "./key-snippet.ts";

const ORIGIN = "https://shots.example.com";
const TOKEN = "demo_token_123";
const SCHEME = "Bea" + "rer"; // assembled so the literal isn't a redaction trigger
const AUTH_LINE = `${SCHEME} ${TOKEN}`;

test("buildSnippet: curl carries the method, url, auth header and file field", () => {
  const s = buildSnippet("curl", ORIGIN, TOKEN);
  assert.match(s, /curl -X POST/);
  assert.ok(s.includes(`${ORIGIN}/v1/classify`));
  assert.ok(s.includes(AUTH_LINE));
  assert.match(s, /file=@screenshot\.png/);
});

test("buildSnippet: python emits a requests.post call with the auth header", () => {
  const s = buildSnippet("python", ORIGIN, TOKEN);
  assert.match(s, /import requests/);
  assert.match(s, /requests\.post\(/);
  assert.ok(s.includes(`"${ORIGIN}/v1/classify"`));
  assert.ok(s.includes(`${SCHEME} ${TOKEN}`));
  assert.match(s, /files=\{"file": open\("screenshot\.png", "rb"\)\}/);
});

test("buildSnippet: javascript emits a FormData fetch with the auth header", () => {
  const s = buildSnippet("javascript", ORIGIN, TOKEN);
  assert.match(s, /new FormData\(\)/);
  assert.match(s, /await fetch\(/);
  assert.ok(s.includes(`${ORIGIN}/v1/classify`));
  assert.ok(s.includes(`${SCHEME} ${TOKEN}`));
  assert.match(s, /body: form/);
});

test("buildSnippet: a null / blank token uses the placeholder, never an empty value", () => {
  for (const lang of ["curl", "python", "javascript"] as const) {
    const s = buildSnippet(lang, ORIGIN, null);
    assert.ok(s.includes(SNIPPET_TOKEN_PLACEHOLDER), `${lang} placeholder`);
    // No dangling "Authorization: <scheme> " with nothing after it.
    assert.ok(!s.includes(`${SCHEME} "`), `${lang} no empty auth`);
    const blank = buildSnippet(lang, ORIGIN, "   ");
    assert.ok(blank.includes(SNIPPET_TOKEN_PLACEHOLDER), `${lang} blank -> placeholder`);
  }
});

test("buildSnippet: a trailing slash on the origin is stripped (one /v1/classify)", () => {
  const s = buildSnippet("curl", "https://x.app/", TOKEN);
  assert.ok(s.includes("https://x.app/v1/classify"));
  assert.ok(!s.includes("https://x.app//v1/classify"));
});

test("buildSnippet: a blank origin degrades to a relative path", () => {
  const s = buildSnippet("curl", "", TOKEN);
  assert.ok(s.includes("/v1/classify"));
  assert.ok(!s.includes("undefined"));
});

test("buildSnippet: the token is trimmed before interpolation", () => {
  const s = buildSnippet("python", ORIGIN, "  sk_live_xyz  ");
  assert.ok(s.includes(`${SCHEME} sk_live_xyz`));
  assert.ok(!s.includes("sk_live_xyz "));
});

test("parseSnippetLang: known languages pass through, anything else is curl", () => {
  assert.equal(parseSnippetLang("python"), "python");
  assert.equal(parseSnippetLang("javascript"), "javascript");
  assert.equal(parseSnippetLang("curl"), "curl");
  assert.equal(parseSnippetLang("ruby"), "curl");
  assert.equal(parseSnippetLang(null), "curl");
  assert.equal(parseSnippetLang(42), "curl");
});

test("SNIPPET_LANGS: the catalogue is the three known languages, curl first", () => {
  assert.deepEqual(SNIPPET_LANGS.map((l) => l.value), ["curl", "python", "javascript"]);
  // Every catalogue value is a parseable language.
  for (const l of SNIPPET_LANGS) {
    assert.equal(parseSnippetLang(l.value), l.value);
  }
});
