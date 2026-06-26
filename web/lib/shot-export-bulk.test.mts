// Pure tests for the bulk shot export serializers (F35). No DOM / clipboard.
import test from "node:test";
import assert from "node:assert/strict";

import {
  toBulkJson,
  toBulkMarkdown,
  toBulkCsv,
  bulkExportToastMessage,
  BULK_CSV_HEADERS,
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

test("bulkExportToastMessage: CSV is a recognised format", () => {
  assert.equal(bulkExportToastMessage(3, 3, "CSV"), "Copied 3 shots as CSV.");
  assert.equal(
    bulkExportToastMessage(2, 5, "CSV"),
    "Copied 2 of 5 selected shots as CSV (the rest are on other pages).",
  );
  assert.equal(bulkExportToastMessage(0, 1, "CSV"), "Nothing to copy as CSV.");
});

test("toBulkCsv: header row + one record per shot, CRLF separated", () => {
  const csv = toBulkCsv([
    shot({ id: "a", primary_category: "receipt", confidence: 0.912, source: "api" }),
    shot({ id: "b", primary_category: "meme", confidence: 0.5, tags: ["fun", "wip"] }),
  ]);
  const lines = csv.split("\r\n");
  assert.equal(lines[0], "id,class,confidence_pct,file,tags,captured,source");
  assert.equal(lines[0], BULK_CSV_HEADERS.join(","));
  assert.equal(lines.length, 3, "header + 2 records");
  // confidence is a bare number (no % sign) for numeric sorting; one decimal.
  assert.ok(lines[1].startsWith("a,receipt,91.2,"));
  assert.ok(lines[2].startsWith("b,meme,50.0,"));
  // multi-tag cell is "; "-joined inside one field.
  assert.ok(lines[2].includes("fun; wip"));
});

test("toBulkCsv: empty selection is just the header (valid CSV, not empty)", () => {
  assert.equal(toBulkCsv([]), BULK_CSV_HEADERS.join(","));
  assert.equal(toBulkCsv(undefined as never), BULK_CSV_HEADERS.join(","));
});

test("toBulkCsv: RFC-4180 quoting -- comma / quote / newline are escaped", () => {
  const csv = toBulkCsv([
    shot({ id: "x", label: 'Lunch, "deluxe"\nrefill', filename: "f.png" }),
  ]);
  const row = csv.split("\r\n")[1];
  // The whole field is wrapped in quotes and the interior quotes are doubled;
  // the embedded newline survives inside the quoted field.
  assert.ok(
    row.includes('"Lunch, ""deluxe""\nrefill"'),
    `unexpected quoting: ${JSON.stringify(row)}`,
  );
});

test("toBulkCsv: a tag containing a comma can't add a phantom column", () => {
  const csv = toBulkCsv([shot({ id: "x", tags: ["a,b", "c"] })]);
  const row = csv.split("\r\n")[1];
  // The tags cell joins as "a,b; c" then gets quoted as one field, so the row
  // keeps exactly the header's column count when parsed leniently.
  assert.ok(row.includes('"a,b; c"'));
});

test("toBulkCsv: prefers label over filename, clamps wild confidence", () => {
  const csv = toBulkCsv([
    shot({ id: "x", label: "  Nice  ", filename: "ugly.png", confidence: 1.7 }),
  ]);
  const row = csv.split("\r\n")[1];
  // Trimmed label wins the file column; the raw filename never appears.
  assert.ok(row.includes(",Nice,"), `file column should hold the label: ${row}`);
  assert.ok(!row.includes("ugly.png"));
  assert.ok(row.includes(",100.0,"), "confidence clamps to 100.0");
});
