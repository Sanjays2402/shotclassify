// Pure tests for the /shots row preview-drawer view-model (F84). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  previewOcr,
  previewConfidences,
  previewRationale,
  buildShotPreview,
  previewHasContent,
  type ShotPreviewRecord,
} from "./shot-preview.ts";

test("previewOcr: prefers nested ocr.text, flattens whitespace", () => {
  const { snippet, truncated } = previewOcr({
    ocr: { text: "  line one\n\nline   two  " },
    ocr_text: "ignored flat text",
  });
  assert.equal(snippet, "line one line two");
  assert.equal(truncated, false);
});

test("previewOcr: falls back to flat ocr_text when nested is empty", () => {
  assert.equal(previewOcr({ ocr: { text: "   " }, ocr_text: "flat wins" }).snippet, "flat wins");
  assert.equal(previewOcr({ ocr_text: "only flat" }).snippet, "only flat");
});

test("previewOcr: null when no text anywhere", () => {
  assert.deepEqual(previewOcr({}), { snippet: null, truncated: false });
  assert.deepEqual(previewOcr({ ocr: { text: "" }, ocr_text: "  " }), {
    snippet: null,
    truncated: false,
  });
});

test("previewOcr: truncates over the cap on a word boundary + reports it", () => {
  const text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet";
  const { snippet, truncated } = previewOcr({ ocr_text: text }, 20);
  assert.equal(truncated, true);
  assert.ok(snippet!.endsWith("…"));
  // Boundary cut: no partial word before the ellipsis.
  assert.ok(snippet!.length <= 21, snippet!);
  assert.ok(!snippet!.slice(0, -1).endsWith(" "));
});

test("previewOcr: text exactly at the cap is not truncated", () => {
  const { snippet, truncated } = previewOcr({ ocr_text: "12345" }, 5);
  assert.equal(snippet, "12345");
  assert.equal(truncated, false);
});

test("previewConfidences: sorts distribution desc, caps, clamps pct", () => {
  const rec: ShotPreviewRecord = {
    classification: {
      confidences: [
        { category: "receipt", score: 0.2 },
        { category: "chat", score: 0.9 },
        { category: "code", score: 0.5 },
        { category: "error", score: 0.05 },
        { category: "other", score: 0.01 },
      ],
    },
  };
  const out = previewConfidences(rec, 3);
  assert.equal(out.length, 3);
  assert.deepEqual(
    out.map((d) => d.category),
    ["chat", "code", "receipt"],
  );
  assert.equal(out[0].pct, 90);
  assert.equal(out[2].pct, 20);
});

test("previewConfidences: drops malformed entries", () => {
  const rec: ShotPreviewRecord = {
    classification: {
      confidences: [
        { category: "good", score: 0.7 },
        { category: "", score: 0.9 },
        { category: "nanscore", score: NaN },
        // @ts-expect-error -- exercising a non-string category at runtime
        { category: 123, score: 0.8 },
      ],
    },
  };
  const out = previewConfidences(rec);
  assert.deepEqual(
    out.map((d) => d.category),
    ["good"],
  );
});

test("previewConfidences: clamps an over-range score to 100%", () => {
  const out = previewConfidences({
    classification: { confidences: [{ category: "x", score: 1.4 }] },
  });
  assert.equal(out[0].pct, 100);
});

test("previewConfidences: synthesises a row from summary when no distribution", () => {
  const out = previewConfidences({ primary_category: "receipt", confidence: 0.83 });
  assert.equal(out.length, 1);
  assert.equal(out[0].category, "receipt");
  assert.equal(out[0].pct, 83);
});

test("previewConfidences: empty when neither distribution nor summary present", () => {
  assert.deepEqual(previewConfidences({}), []);
  assert.deepEqual(previewConfidences({ classification: { confidences: [] } }), []);
});

test("previewRationale: trims, null when blank/absent", () => {
  assert.equal(previewRationale({ classification: { rationale: "  reads as a tip line  " } }), "reads as a tip line");
  assert.equal(previewRationale({ classification: { rationale: "   " } }), null);
  assert.equal(previewRationale({}), null);
});

test("buildShotPreview: assembles the full model", () => {
  const rec: ShotPreviewRecord = {
    ocr_text: "TOTAL 12.00",
    classification: {
      confidences: [
        { category: "receipt", score: 0.95 },
        { category: "chat", score: 0.05 },
      ],
      rationale: "Has a total line.",
    },
  };
  const m = buildShotPreview(rec);
  assert.equal(m.ocrSnippet, "TOTAL 12.00");
  assert.equal(m.ocrTruncated, false);
  assert.equal(m.topConfidences[0].category, "receipt");
  assert.equal(m.rationale, "Has a total line.");
  assert.equal(previewHasContent(m), true);
});

test("previewHasContent: false for a wholly empty record", () => {
  const m = buildShotPreview({});
  assert.equal(m.ocrSnippet, null);
  assert.deepEqual(m.topConfidences, []);
  assert.equal(m.rationale, null);
  assert.equal(previewHasContent(m), false);
});

test("previewHasContent: true when only a synthetic confidence row exists", () => {
  const m = buildShotPreview({ primary_category: "code", confidence: 0.6 });
  assert.equal(previewHasContent(m), true);
});
