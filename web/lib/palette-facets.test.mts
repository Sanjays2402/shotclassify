// Pure tests for the command-palette facet parser. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseFacets,
  resolveCategory,
  parseConfValue,
  hasFacets,
  facetsToHistoryParams,
  describeFacets,
  stripFacets,
} from "./palette-facets.ts";

test("resolveCategory: enum value, short label, and aliases all resolve", () => {
  assert.equal(resolveCategory("receipt"), "receipt");
  assert.equal(resolveCategory("code_snippet"), "code_snippet");
  assert.equal(resolveCategory("code"), "code_snippet");
  assert.equal(resolveCategory("ERROR"), "error_stacktrace");
  assert.equal(resolveCategory("stacktrace"), "error_stacktrace");
  assert.equal(resolveCategory("chat"), "chat_screenshot");
  assert.equal(resolveCategory("ui"), "ui_mockup");
  assert.equal(resolveCategory("doc"), "document");
  assert.equal(resolveCategory("nonsense"), undefined);
});

test("resolveCategory: tolerates spaces / hyphens", () => {
  assert.equal(resolveCategory("code snippet"), "code_snippet");
  assert.equal(resolveCategory("ui-mockup"), "ui_mockup");
});

test("parseConfValue: percents, fractions, and bad input", () => {
  assert.equal(parseConfValue("90"), 0.9);
  assert.equal(parseConfValue("90%"), 0.9);
  assert.equal(parseConfValue("0.8"), 0.8);
  assert.equal(parseConfValue("100"), 1);
  assert.equal(parseConfValue("1"), 1);
  assert.equal(parseConfValue("0"), 0);
  assert.equal(parseConfValue("abc"), undefined);
  assert.equal(parseConfValue("150"), undefined); // 1.5 out of range
  assert.equal(parseConfValue(""), undefined);
});

test("parseFacets: class: facet pulled out, residual text preserved", () => {
  const f = parseFacets("class:receipt uber eats");
  assert.equal(f.category, "receipt");
  assert.equal(f.text, "uber eats");
  assert.ok(hasFacets(f));
});

test("parseFacets: category:/in: synonyms work", () => {
  assert.equal(parseFacets("category:code").category, "code_snippet");
  assert.equal(parseFacets("in:error").category, "error_stacktrace");
});

test("parseFacets: unresolved class token degrades to search text", () => {
  const f = parseFacets("class:bogus hello");
  assert.equal(f.category, undefined);
  // The value survives as plain text so the search still does something.
  assert.match(f.text, /bogus/);
  assert.match(f.text, /hello/);
});

test("parseFacets: comparison tokens set conf floor / ceiling", () => {
  const gt = parseFacets(">90%");
  assert.equal(gt.minConf, 0.9);
  assert.equal(gt.maxConf, undefined);

  const ge = parseFacets(">=0.75 receipt");
  assert.equal(ge.minConf, 0.75);
  assert.equal(ge.text, "receipt");

  const lt = parseFacets("<50%");
  assert.equal(lt.maxConf, 0.5);
  assert.equal(lt.minConf, undefined);
});

test("parseFacets: conf:/confidence: keyword sets a floor", () => {
  assert.equal(parseFacets("conf:80").minConf, 0.8);
  assert.equal(parseFacets("confidence:0.6").minConf, 0.6);
  // Bad value falls back to residual text.
  assert.match(parseFacets("conf:nope find").text, /conf:nope/);
});

test("parseFacets: tag: and #tag both set the tag facet", () => {
  assert.equal(parseFacets("tag:urgent").tag, "urgent");
  assert.equal(parseFacets("#Important").tag, "important"); // lowercased
});

test("parseFacets: combined facets + residual", () => {
  const f = parseFacets("class:receipt >85% tag:reimburse coffee");
  assert.equal(f.category, "receipt");
  assert.equal(f.minConf, 0.85);
  assert.equal(f.tag, "reimburse");
  assert.equal(f.text, "coffee");
});

test("parseFacets: plain query has no facets", () => {
  const f = parseFacets("just some words");
  assert.equal(hasFacets(f), false);
  assert.equal(f.text, "just some words");
});

test("facetsToHistoryParams: maps facets to API query shape", () => {
  const f = parseFacets("class:code >70% tag:x rest");
  const p = facetsToHistoryParams(f, 10);
  assert.equal(p.limit, 10);
  assert.equal(p.category, "code_snippet");
  assert.equal(p.min_conf, 0.7);
  assert.equal(p.tag, "x");
  assert.equal(p.q, "rest");
});

test("facetsToHistoryParams: empty text becomes undefined q", () => {
  const f = parseFacets("class:meme");
  const p = facetsToHistoryParams(f);
  assert.equal(p.q, undefined);
  assert.equal(p.category, "meme");
});

test("describeFacets: builds a readable summary, empty when none", () => {
  assert.equal(describeFacets(parseFacets("hello")), "");
  const s = describeFacets(parseFacets("class:receipt >90% tag:x"));
  assert.match(s, /class receipt/);
  assert.match(s, />=90%/);
  assert.match(s, /#x/);
});

test("stripFacets: removes facet tokens, keeps residual free text", () => {
  assert.equal(stripFacets("class:receipt >90% coffee shop"), "coffee shop");
  assert.equal(stripFacets("tag:urgent ledger"), "ledger");
  assert.equal(stripFacets("invoice <50% #draft total"), "invoice total");
});

test("stripFacets: pure-facet query strips to empty", () => {
  assert.equal(stripFacets("class:receipt >90% tag:x"), "");
  assert.equal(stripFacets("class:code"), "");
});

test("stripFacets: no-facet query is just trimmed, otherwise unchanged", () => {
  assert.equal(stripFacets("just some words"), "just some words");
  assert.equal(stripFacets("  spaced out  "), "spaced out");
});

test("stripFacets: idempotent (re-stripping a stripped query is stable)", () => {
  const once = stripFacets("class:receipt >90% coffee shop");
  assert.equal(stripFacets(once), once);
});

test("stripFacets: unresolved class: keeps the value as search text", () => {
  // parseFacets drops the `class:` prefix on an unknown category and keeps the
  // value -- stripFacets inherits that, so a typo'd facet isn't silently lost.
  assert.equal(stripFacets("class:nonsense ledger"), "nonsense ledger");
});

test("stripFacets: non-string input is safe", () => {
  assert.equal(stripFacets(null as never), "");
  assert.equal(stripFacets(undefined as never), "");
});
