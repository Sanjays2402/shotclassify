// Pure tests for the shot-detail export serializers. No DOM, no clipboard.
import test from "node:test";
import assert from "node:assert/strict";

import {
  toExportObject,
  toJson,
  toMarkdown,
  type ShotExportInput,
} from "./shot-export.ts";

const FULL: ShotExportInput = {
  id: "abc12345def",
  filename: "receipt-uber.png",
  created_at: "2026-06-24T18:30:00Z",
  primary_category: "receipt",
  confidence: 0.917,
  elapsed_ms: 412,
  source: "upload",
  label: "Uber ride home",
  tags: ["important", "reimburse"],
  user_corrected_to: null,
  ocr_text: "UBER\nTotal $24.30\nThanks for riding",
  rationale: "Layout + total line + merchant name say receipt.",
  distribution: [
    { category: "receipt", score: 0.917 },
    { category: "document", score: 0.05 },
    { category: "other", score: 0.033 },
  ],
};

test("toExportObject: includes core fields and clamps confidence", () => {
  const o = toExportObject({ ...FULL, confidence: 1.5 });
  assert.equal(o.id, "abc12345def");
  assert.equal(o.primary_category, "receipt");
  assert.equal(o.confidence, 1); // clamped to <= 1
  assert.equal(o.confidence_pct, 100);
});

test("toExportObject: omits empty optional slots", () => {
  const o = toExportObject({
    id: "x",
    filename: "f.png",
    primary_category: "other",
    confidence: 0.4,
    label: "   ",
    tags: [],
    ocr_text: "",
    rationale: "  ",
  });
  assert.ok(!("label" in o));
  assert.ok(!("tags" in o));
  assert.ok(!("ocr_text" in o));
  assert.ok(!("rationale" in o));
  assert.ok(!("user_corrected_to" in o));
  assert.ok(!("distribution" in o));
});

test("toExportObject: distribution is sorted high-to-low", () => {
  const o = toExportObject({
    ...FULL,
    distribution: [
      { category: "a", score: 0.1 },
      { category: "b", score: 0.7 },
      { category: "c", score: 0.2 },
    ],
  });
  const dist = o.distribution as { category: string; score: number }[];
  assert.deepEqual(dist.map((d) => d.category), ["b", "c", "a"]);
  assert.equal(dist[0].score, 70);
});

test("toJson: valid, pretty-printed, round-trips", () => {
  const json = toJson(FULL);
  assert.ok(json.includes("\n  ")); // 2-space indent
  const parsed = JSON.parse(json);
  assert.equal(parsed.id, "abc12345def");
  assert.equal(parsed.confidence_pct, 91.7);
  assert.equal(parsed.tags.length, 2);
});

test("toMarkdown: has heading, summary table, and fenced OCR", () => {
  const md = toMarkdown(FULL);
  assert.match(md, /^# Shot abc12345def — Uber ride home/);
  assert.match(md, /\| Class \| `receipt` \|/);
  assert.match(md, /\| Confidence \| 91\.7% \|/);
  assert.match(md, /## Confidence distribution/);
  assert.match(md, /## OCR transcript/);
  assert.match(md, /```\nUBER\nTotal \$24\.30/);
});

test("toMarkdown: omits sections that have no data", () => {
  const md = toMarkdown({
    id: "y",
    filename: "f.png",
    primary_category: "other",
    confidence: 0.5,
  });
  assert.doesNotMatch(md, /## Confidence distribution/);
  assert.doesNotMatch(md, /## OCR transcript/);
  assert.doesNotMatch(md, /## Rationale/);
  // Falls back to filename in the heading when no label.
  assert.match(md, /^# Shot y — f\.png/);
});

test("toMarkdown: escapes pipes so a table row can't be broken", () => {
  const md = toMarkdown({
    id: "z",
    filename: "a|b|c.png",
    primary_category: "receipt",
    confidence: 0.8,
    label: "pipe | name",
  });
  assert.match(md, /a\\\|b\\\|c\.png/);
  assert.match(md, /pipe \\\| name/);
});

test("toMarkdown: rationale is rendered as a blockquote, multi-line", () => {
  const md = toMarkdown({
    id: "q",
    filename: "f.png",
    primary_category: "error_stacktrace",
    confidence: 0.7,
    rationale: "line one\nline two",
  });
  assert.match(md, /> line one\n> line two/);
});

test("toMarkdown: corrected-to row appears only when set", () => {
  const withCorrection = toMarkdown({ ...FULL, user_corrected_to: "document" });
  assert.match(withCorrection, /\| Corrected to \| `document` \|/);
  const without = toMarkdown(FULL);
  assert.doesNotMatch(without, /Corrected to/);
});
