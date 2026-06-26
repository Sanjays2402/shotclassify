// Pure tests for the bulk shot export serializers (F35). No DOM / clipboard.
import test from "node:test";
import assert from "node:assert/strict";

import {
  toBulkJson,
  toBulkMarkdown,
  bulkExportToastMessage,
} from "./shot-export-bulk.ts";
import type { ShotExportInput } from "./shot-export.ts";

function shot(over: Partial<ShotExportInput>): ShotExportInput {
  return {
    id: "abc123",
    filename: "shot.png",
    primary_category: "receipt",
    confidence: 0.9,
    ...over,
  };
}

test("toBulkJson: an array of per-shot export objects", () => {
  const out = toBulkJson([
    shot({ id: "a", confidence: 0.5 }),
    shot({ id: "b", confidence: 0.8, tags: ["x"] }),
  ]);
  const parsed = JSON.parse(out);
  assert.ok(Array.isArray(parsed));
  assert.equal(parsed.length, 2);
  assert.equal(parsed[0].id, "a");
  assert.equal(parsed[1].id, "b");
  // Reuses the single-shot exporter, so confidence_pct is present.
  assert.equal(parsed[1].confidence_pct, 80);
  assert.deepEqual(parsed[1].tags, ["x"]);
});

test("toBulkJson: empty selection serialises to []", () => {
  assert.equal(toBulkJson([]), "[]");
  assert.equal(toBulkJson(undefined as never), "[]");
});

test("toBulkJson: pretty-printed (2-space indent)", () => {
  const out = toBulkJson([shot({ id: "a" })]);
  assert.ok(out.includes('\n  {'), "expected indented array entries");
});

test("toBulkMarkdown: a heading + one summary row per shot", () => {
  const md = toBulkMarkdown([
    shot({ id: "a", primary_category: "receipt", confidence: 0.912 }),
    shot({ id: "b", primary_category: "meme", confidence: 0.5, tags: ["fun", "wip"] }),
  ]);
  assert.ok(md.startsWith("# 2 shots\n"));
  assert.ok(md.includes("| ID | Class | Confidence | File | Tags |"));
  assert.ok(md.includes("| a | `receipt` | 91.2% |"));
  assert.ok(md.includes("| b | `meme` | 50.0% |"));
  // Tags rendered as code spans; missing tags become an em dash.
  assert.ok(md.includes("`fun`, `wip`"));
  assert.ok(md.includes("| — |"));
});

test("toBulkMarkdown: singular heading for one shot", () => {
  const md = toBulkMarkdown([shot({ id: "solo" })]);
  assert.ok(md.startsWith("# 1 shot\n"));
});

test("toBulkMarkdown: empty selection is an explicit note, not a broken table", () => {
  const md = toBulkMarkdown([]);
  assert.ok(md.includes("# 0 shots"));
  assert.ok(md.includes("(no shots selected)"));
  assert.ok(!md.includes("| ID |"), "should not render a header-only table");
});

test("toBulkMarkdown: pipes / newlines in a label can't break the row", () => {
  const md = toBulkMarkdown([
    shot({ id: "x", label: "a | b\nsecond line", filename: "f.png" }),
  ]);
  const row = md.split("\n").find((l) => l.startsWith("| x |"))!;
  assert.ok(row.includes("a \\| b second line"));
  // The row keeps exactly 6 UNESCAPED column-separator pipes; the pipe inside
  // the cell is escaped as \| so a renderer won't read it as a new column.
  const colSeps = (row.match(/(?<!\\)\|/g) || []).length;
  assert.equal(colSeps, 6);
});

test("toBulkMarkdown: prefers label over filename, clamps wild confidence", () => {
  const md = toBulkMarkdown([
    shot({ id: "x", label: "  Nice name  ", filename: "ugly.png", confidence: 1.7 }),
  ]);
  assert.ok(md.includes("Nice name"));
  assert.ok(!md.includes("ugly.png"));
  assert.ok(md.includes("100.0%"), "confidence clamps to 100%");
});

test("bulkExportToastMessage: full copy names the count + format", () => {
  assert.equal(bulkExportToastMessage(3, 3, "JSON"), "Copied 3 shots as JSON.");
  assert.equal(bulkExportToastMessage(1, 1, "Markdown"), "Copied 1 shot as Markdown.");
});

test("bulkExportToastMessage: partial copy is honest about cross-page selection", () => {
  assert.equal(
    bulkExportToastMessage(2, 5, "JSON"),
    "Copied 2 of 5 selected shots as JSON (the rest are on other pages).",
  );
});

test("bulkExportToastMessage: nothing to copy", () => {
  assert.equal(bulkExportToastMessage(0, 4, "Markdown"), "Nothing to copy as Markdown.");
  assert.equal(bulkExportToastMessage(0, 0, "JSON"), "Nothing to copy as JSON.");
});
