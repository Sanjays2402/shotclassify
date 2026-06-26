// Bulk "copy as JSON / Markdown" for a multi-select on /shots (F35). The
// shot-detail page can already copy ONE shot as JSON / Markdown
// (lib/shot-export.ts); this extends the same serializers to the bulk
// selection so you can grab a manifest of everything you ticked. Pure +
// framework-free so the formatting is unit-testable; the page wraps these
// with the clipboard API + a toast.
//
// JSON output is an array of the same per-shot export objects the single
// export emits (machine-consumable). Markdown output is ONE compact summary
// table -- far more paste-friendly for a bulk selection than N full
// documents -- listing class / confidence / file / tags / captured per row.

import {
  toExportObject,
  type ShotExportInput,
} from "./shot-export";

// Pretty-printed JSON array of the selected shots' export objects. An empty
// selection serialises to "[]" so the caller never copies "undefined".
export function toBulkJson(shots: readonly ShotExportInput[]): string {
  const list = Array.isArray(shots) ? shots : [];
  return JSON.stringify(list.map(toExportObject), null, 2);
}

// Round a 0..1 score to a clamped whole-ish percent for the summary table.
function pct1(score: number): string {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(score) ? score : 0));
  return `${(clamped * 100).toFixed(1)}%`;
}

// Escape pipe / newline so a value can't break a Markdown table row.
function mdCell(v: string): string {
  return v.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

// A compact Markdown summary table for the selection. Heading names the
// count; one row per shot. Empty selection yields a heading + an explicit
// "(no shots selected)" line rather than a broken empty table.
export function toBulkMarkdown(shots: readonly ShotExportInput[]): string {
  const list = Array.isArray(shots) ? shots : [];
  const lines: string[] = [];
  lines.push(`# ${list.length} shot${list.length === 1 ? "" : "s"}`);
  lines.push("");
  if (list.length === 0) {
    lines.push("_(no shots selected)_");
    lines.push("");
    return lines.join("\n");
  }
  lines.push("| ID | Class | Confidence | File | Tags |");
  lines.push("| --- | --- | --- | --- | --- |");
  for (const s of list) {
    const id = mdCell(s.id ?? "");
    const cls = `\`${mdCell(s.primary_category ?? "")}\``;
    const conf = pct1(s.confidence);
    const file = mdCell((s.label && s.label.trim()) || s.filename || "");
    const tags =
      s.tags && s.tags.length > 0
        ? s.tags.map((t: string) => `\`${mdCell(t)}\``).join(", ")
        : "—";
    lines.push(`| ${id} | ${cls} | ${conf} | ${file} | ${tags} |`);
  }
  lines.push("");
  return lines.join("\n");
}

// Toast copy for a bulk export. Honest about partial coverage: a multi-page
// selection can include ids that aren't on the current page, so the page can
// only serialise the rows it actually holds. Names the format and the
// copied/selected split when they differ.
export function bulkExportToastMessage(
  copied: number,
  selected: number,
  format: "JSON" | "Markdown" | "CSV",
): string {
  const c = Math.max(0, Math.floor(Number.isFinite(copied) ? copied : 0));
  const sel = Math.max(c, Math.floor(Number.isFinite(selected) ? selected : c));
  const noun = `shot${c === 1 ? "" : "s"}`;
  if (c === 0) return `Nothing to copy as ${format}.`;
  if (c < sel) {
    return `Copied ${c} of ${sel} selected ${noun} as ${format} (the rest are on other pages).`;
  }
  return `Copied ${c} ${noun} as ${format}.`;
}

// RFC-4180 field quoting. A field is wrapped in double quotes when it contains
// a comma, a double quote, a CR, or an LF (§2.5-2.7); interior double quotes
// are escaped by doubling them. Everything else passes through untouched so a
// plain value stays unquoted and human-readable.
function csvCell(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

// The CSV column order. Stable + documented so downstream scripts can rely on
// it. `confidence_pct` is a bare number (no % sign) so a spreadsheet sorts it
// numerically; tags are joined with "; " inside a single cell.
export const BULK_CSV_HEADERS = [
  "id",
  "class",
  "confidence_pct",
  "file",
  "tags",
  "captured",
  "source",
] as const;

// A flat, spreadsheet-friendly CSV of the selection (F64) -- the third bulk
// export format beside JSON (machine-nested) and Markdown (paste-into-issue).
// RFC-4180 throughout: CRLF record separators (§2.1) and per-field quoting via
// csvCell, so a label/filename containing a comma, quote, or newline can't
// corrupt the columns. Always emits the header row; an empty selection yields
// the header alone (a valid, self-describing CSV) rather than an empty string.
export function toBulkCsv(shots: readonly ShotExportInput[]): string {
  const list = Array.isArray(shots) ? shots : [];
  const rows: string[] = [BULK_CSV_HEADERS.join(",")];
  for (const s of list) {
    const conf = Math.max(
      0,
      Math.min(1, Number.isFinite(s.confidence) ? s.confidence : 0),
    );
    const cells = [
      s.id ?? "",
      s.primary_category ?? "",
      (conf * 100).toFixed(1),
      (s.label && s.label.trim()) || s.filename || "",
      s.tags && s.tags.length > 0 ? s.tags.join("; ") : "",
      s.created_at ?? "",
      s.source ?? "",
    ];
    rows.push(cells.map((c) => csvCell(String(c))).join(","));
  }
  return rows.join("\r\n");
}
