// Pure tests for the /stats category-legend popover helpers. No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  totalCount,
  categoryLegendSummary,
  categoryLegendSummaries,
  type PerClassRow,
} from "./category-legend.ts";

const ROWS: PerClassRow[] = [
  { category: "receipt", count: 50, mean_confidence: 0.9 },
  { category: "code_snippet", count: 30, mean_confidence: 0.85 },
  { category: "meme", count: 20, mean_confidence: 0.6 },
];

test("totalCount: sums counts, tolerates bad rows", () => {
  assert.equal(totalCount(ROWS), 100);
  assert.equal(totalCount([]), 0);
  assert.equal(totalCount(null), 0);
  assert.equal(
    totalCount([
      { category: "receipt", count: 10, mean_confidence: 0.9 },
      { category: "meme", count: NaN as unknown as number, mean_confidence: 0.5 },
      { category: "other", count: -5, mean_confidence: 0.4 },
    ]),
    10,
  );
});

test("categoryLegendSummary: share is count / total, formatted", () => {
  const s = categoryLegendSummary(ROWS[0], 100);
  assert.equal(s.category, "receipt");
  assert.equal(s.label, "Receipt");
  assert.equal(s.count, 50);
  assert.equal(s.share, 0.5);
  assert.equal(s.sharePct, "50.0%");
});

test("categoryLegendSummary: mean confidence is clamped + formatted", () => {
  const s = categoryLegendSummary(ROWS[1], 100);
  assert.equal(s.meanConfidence, 0.85);
  assert.equal(s.meanConfidencePct, "85%");

  // Out-of-range values clamp to [0,1].
  const over = categoryLegendSummary(
    { category: "receipt", count: 1, mean_confidence: 1.4 },
    10,
  );
  assert.equal(over.meanConfidence, 1);
  assert.equal(over.meanConfidencePct, "100%");
  const under = categoryLegendSummary(
    { category: "receipt", count: 1, mean_confidence: -0.2 },
    10,
  );
  assert.equal(under.meanConfidence, 0);
});

test("categoryLegendSummary: zero total yields 0% share, not NaN", () => {
  const s = categoryLegendSummary({ category: "receipt", count: 0, mean_confidence: 0.5 }, 0);
  assert.equal(s.share, 0);
  assert.equal(s.sharePct, "0.0%");
});

test("categoryLegendSummary: builds the /shots deep link", () => {
  const s = categoryLegendSummary(ROWS[1], 100);
  assert.equal(s.shotsHref, "/shots?category=code_snippet");
});

test("categoryLegendSummary: negative / NaN count coerces to 0", () => {
  const s = categoryLegendSummary(
    { category: "meme", count: -7, mean_confidence: 0.5 },
    100,
  );
  assert.equal(s.count, 0);
  assert.equal(s.share, 0);
});

test("categoryLegendSummaries: maps the whole array sharing one total", () => {
  const all = categoryLegendSummaries(ROWS);
  assert.equal(all.length, 3);
  assert.equal(all[0].sharePct, "50.0%");
  assert.equal(all[1].sharePct, "30.0%");
  assert.equal(all[2].sharePct, "20.0%");
  // Order preserved.
  assert.deepEqual(all.map((s) => s.category), ["receipt", "code_snippet", "meme"]);
});

test("categoryLegendSummaries: empty / null yields []", () => {
  assert.deepEqual(categoryLegendSummaries([]), []);
  assert.deepEqual(categoryLegendSummaries(null), []);
  assert.deepEqual(categoryLegendSummaries(undefined), []);
});
