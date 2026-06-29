// Pure tests for the /compare share-link helpers (this tick). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  canShareCompare,
  buildCompareLink,
  compareShareToastMessage,
} from "./compare-link.ts";

const A = "11111111-2222-3333-4444-555555555555";
const B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

test("canShareCompare: both sides required, trimmed, null-safe", () => {
  assert.equal(canShareCompare(A, B), true);
  assert.equal(canShareCompare(A, ""), false);
  assert.equal(canShareCompare("", B), false);
  assert.equal(canShareCompare(null, undefined), false);
  assert.equal(canShareCompare("  ", A), false);
  // Same id on both sides is a legitimate (unusual) link.
  assert.equal(canShareCompare(A, A), true);
});

test("buildCompareLink: emits FULL ids, never truncated", () => {
  const url = buildCompareLink(A, B);
  assert.equal(url, `/compare?a=${A}&b=${B}`);
  // The whole 36-char id survives -- the old shortId path cut it to 8.
  assert.ok(url.includes(A));
  assert.ok(url.includes(B));
});

test("buildCompareLink: stable a-then-b order regardless of arg trimming", () => {
  assert.equal(
    buildCompareLink(`  ${A}  `, `  ${B}  `),
    `/compare?a=${A}&b=${B}`,
  );
});

test("buildCompareLink: one-sided selection yields a partial but valid link", () => {
  assert.equal(buildCompareLink(A, ""), `/compare?a=${A}`);
  assert.equal(buildCompareLink("", B), `/compare?b=${B}`);
});

test("buildCompareLink: empty selection collapses to a bare /compare", () => {
  assert.equal(buildCompareLink("", ""), "/compare");
  assert.equal(buildCompareLink(null, undefined), "/compare");
});

test("buildCompareLink: base origin is prefixed verbatim for the clipboard", () => {
  assert.equal(
    buildCompareLink(A, B, "https://shotclassify.app"),
    `https://shotclassify.app/compare?a=${A}&b=${B}`,
  );
});

test("buildCompareLink: special chars in an id are percent-encoded", () => {
  // URLSearchParams encodes -- so a stray space can't break the query.
  assert.equal(buildCompareLink("a b", "c"), "/compare?a=a+b&b=c");
});

test("compareShareToastMessage: names how many sides the link carries", () => {
  assert.match(compareShareToastMessage(A, B), /comparison/);
  assert.match(compareShareToastMessage(A, ""), /shot\b/);
  assert.match(compareShareToastMessage("", ""), /shot\b/);
});
