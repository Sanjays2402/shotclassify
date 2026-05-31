// Tests for the embed HTML renderer. Verifies safe escaping, that
// the primary category is highlighted, and that the iframe-friendly
// markup contains no app chrome.
import test from "node:test";
import assert from "node:assert/strict";

const { renderEmbedHtml, topDistribution } = await import("./embed.ts");

type AnyRec = Parameters<typeof renderEmbedHtml>[0];

function makeRec(over: Partial<AnyRec> = {}): AnyRec {
  return {
    id: "abc123de",
    filename: "screenshot.png",
    created_at: new Date("2024-01-01T00:00:00Z").toISOString(),
    primary_category: "receipt",
    confidence: 0.92,
    source: "api",
    classification: {
      primary: "receipt",
      confidences: [
        { category: "receipt", score: 0.92 },
        { category: "document", score: 0.05 },
        { category: "chart", score: 0.02 },
        { category: "other", score: 0.01 },
      ],
    },
    ...over,
  } as AnyRec;
}

test("renderEmbedHtml: includes primary label, confidence, and shortId", () => {
  const html = renderEmbedHtml(makeRec());
  assert.match(html, /Receipt/);
  assert.match(html, /92\.0%/);
  assert.match(html, /abc123de/);
  // Footer points at the canonical share page.
  assert.match(html, /href="\/r\/abc123de"/);
});

test("renderEmbedHtml: escapes hostile filenames", () => {
  const html = renderEmbedHtml(
    makeRec({ filename: '<script>alert(1)</script>"><img>' }),
  );
  assert.ok(
    !html.includes("<script>alert(1)</script>"),
    "raw script tag must not appear",
  );
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /&quot;/);
});

test("renderEmbedHtml: ships no app chrome and no JS", () => {
  const html = renderEmbedHtml(makeRec());
  assert.ok(
    !html.includes("SHOTCLASSIFY"),
    "header brand mark must not leak in",
  );
  assert.ok(
    !html.includes("CommandPalette"),
    "app components must not be referenced",
  );
  // Page is allowed exactly zero <script> elements.
  assert.equal(
    (html.match(/<script\b/gi) ?? []).length,
    0,
    "embed must be script-free",
  );
});

test("renderEmbedHtml: respects 404-ish empty filename", () => {
  const html = renderEmbedHtml(makeRec({ filename: "" }));
  assert.match(html, /no filename/);
});

test("topDistribution: returns up to n entries sorted desc", () => {
  const top = topDistribution(makeRec(), 3);
  assert.equal(top.length, 3);
  assert.deepEqual(
    top.map((d) => d.category),
    ["receipt", "document", "chart"],
  );
  assert.ok(top[0].score >= top[1].score);
  assert.ok(top[1].score >= top[2].score);
});

test("topDistribution: synthesises a distribution when none provided", () => {
  const rec = makeRec({ classification: undefined });
  const top = topDistribution(rec, 4);
  assert.equal(top.length, 4);
  assert.equal(top[0].category, "receipt");
  // Synthesised primary score equals raw confidence.
  assert.equal(top[0].score, 0.92);
});
