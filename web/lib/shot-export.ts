// Pure serializers for the shot-detail "copy as JSON / Markdown" export.
// Framework-free so the formatting is unit-testable without a DOM. The
// component in components/CopyExportButtons.tsx wraps these with the
// clipboard API. Output is designed to paste cleanly into a GitHub/Linear
// issue (Markdown) or a script / bug report (JSON).

export type ShotExportConfidence = {
  category: string;
  score: number;
};

// The subset of the shot-detail record the exporters consume. Mirrors the
// page's `Detail` type but only the fields worth exporting.
export type ShotExportInput = {
  id: string;
  filename: string;
  created_at?: string;
  primary_category: string;
  confidence: number;
  elapsed_ms?: number | null;
  source?: string | null;
  label?: string | null;
  tags?: string[];
  user_corrected_to?: string | null;
  ocr_text?: string | null;
  rationale?: string | null;
  distribution?: ShotExportConfidence[];
};

// Round a 0..1 score to a stable percentage number (one decimal). Clamped so
// a stray >1 score never serialises as 137%.
function pctNum(score: number, digits = 1): number {
  const clamped = Math.max(0, Math.min(1, score));
  return Number((clamped * 100).toFixed(digits));
}

// Build a plain, JSON-serialisable object. Stable key order, omits empty
// slots so the payload stays tight. `distribution` is sorted high-to-low.
export function toExportObject(s: ShotExportInput): Record<string, unknown> {
  const obj: Record<string, unknown> = {
    id: s.id,
    filename: s.filename,
    primary_category: s.primary_category,
    confidence: pctNum(s.confidence, 2) / 100, // keep 0..1 but clamped/rounded
    confidence_pct: pctNum(s.confidence, 1),
  };
  if (s.created_at) obj.created_at = s.created_at;
  if (typeof s.elapsed_ms === "number") obj.elapsed_ms = s.elapsed_ms;
  if (s.source) obj.source = s.source;
  if (s.label && s.label.trim()) obj.label = s.label.trim();
  if (s.tags && s.tags.length > 0) obj.tags = [...s.tags];
  if (s.user_corrected_to) obj.user_corrected_to = s.user_corrected_to;
  if (s.distribution && s.distribution.length > 0) {
    obj.distribution = [...s.distribution]
      .sort((a, b) => b.score - a.score)
      .map((d) => ({ category: d.category, score: pctNum(d.score, 2) }));
  }
  if (s.ocr_text && s.ocr_text.trim()) obj.ocr_text = s.ocr_text;
  if (s.rationale && s.rationale.trim()) obj.rationale = s.rationale.trim();
  return obj;
}

// Pretty-printed JSON (2-space indent) for the "copy as JSON" button.
export function toJson(s: ShotExportInput): string {
  return JSON.stringify(toExportObject(s), null, 2);
}

// Escape pipe characters so OCR text / labels don't break a Markdown table
// row. Newlines in a cell are replaced with a <br> so the row stays intact.
function mdCell(v: string): string {
  return v.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

// Build a Markdown document suitable for pasting into an issue. A heading,
// a key/value summary table, the confidence distribution as a table, and the
// OCR + rationale as fenced / quoted blocks. Empty sections are omitted.
export function toMarkdown(s: ShotExportInput): string {
  const title = (s.label && s.label.trim()) || s.filename;
  const lines: string[] = [];
  lines.push(`# Shot ${s.id} — ${mdCell(title)}`);
  lines.push("");
  lines.push("| Field | Value |");
  lines.push("| --- | --- |");
  lines.push(`| Class | \`${mdCell(s.primary_category)}\` |`);
  lines.push(`| Confidence | ${pctNum(s.confidence, 1)}% |`);
  if (s.user_corrected_to)
    lines.push(`| Corrected to | \`${mdCell(s.user_corrected_to)}\` |`);
  if (s.created_at) lines.push(`| Captured | ${mdCell(s.created_at)} |`);
  if (s.source) lines.push(`| Source | ${mdCell(s.source)} |`);
  if (typeof s.elapsed_ms === "number")
    lines.push(`| Latency | ${s.elapsed_ms} ms |`);
  lines.push(`| File | ${mdCell(s.filename)} |`);
  if (s.tags && s.tags.length > 0)
    lines.push(`| Tags | ${s.tags.map((t) => `\`${mdCell(t)}\``).join(", ")} |`);

  const dist = s.distribution
    ? [...s.distribution].sort((a, b) => b.score - a.score)
    : [];
  if (dist.length > 0) {
    lines.push("");
    lines.push("## Confidence distribution");
    lines.push("");
    lines.push("| Class | Score |");
    lines.push("| --- | --- |");
    for (const d of dist) {
      lines.push(`| \`${mdCell(d.category)}\` | ${pctNum(d.score, 2)}% |`);
    }
  }

  if (s.rationale && s.rationale.trim()) {
    lines.push("");
    lines.push("## Rationale");
    lines.push("");
    lines.push(
      s.rationale
        .trim()
        .split(/\r?\n/)
        .map((l) => `> ${l}`)
        .join("\n"),
    );
  }

  if (s.ocr_text && s.ocr_text.trim()) {
    lines.push("");
    lines.push("## OCR transcript");
    lines.push("");
    lines.push("```");
    lines.push(s.ocr_text.replace(/\r\n/g, "\n").trimEnd());
    lines.push("```");
  }

  lines.push("");
  return lines.join("\n");
}

// --- CSV (shared single + bulk) ------------------------------------------
// These primitives are the SINGLE source of truth for the flat CSV export so
// the shot-detail single-shot CSV (F80) and the /shots bulk CSV (F64) can't
// drift apart. shot-export-bulk.ts imports csvCell + csvRow + CSV_HEADERS
// from here and re-exports the headers under its historical BULK_CSV_HEADERS
// name. Same columns, same quoting, same row shape for both surfaces.

// RFC-4180 field quoting. A field is wrapped in double quotes when it contains
// a comma, a double quote, a CR, or an LF (sec 2.5-2.7); interior double quotes
// are escaped by doubling them. Everything else passes through untouched so a
// plain value stays unquoted and human-readable.
export function csvCell(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

// The canonical CSV column order. Stable + documented so downstream scripts
// can rely on it. `confidence_pct` is a bare number (no % sign) so a
// spreadsheet sorts it numerically; tags are joined with "; " inside a single
// cell.
export const CSV_HEADERS = [
  "id",
  "class",
  "confidence_pct",
  "file",
  "tags",
  "captured",
  "source",
] as const;

// One fully-quoted CSV record for a shot, in CSV_HEADERS order. Confidence is
// clamped 0..1 then printed as a bare one-decimal percent; the file column
// prefers a trimmed label over the filename; tags collapse to a "; "-joined
// cell. Every field passes through csvCell so a comma / quote / newline can't
// corrupt the columns.
export function csvRow(s: ShotExportInput): string {
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
  return cells.map((c) => csvCell(String(c))).join(",");
}

// A flat, spreadsheet-friendly CSV of ONE shot (F80) -- the third single-shot
// export format beside JSON and Markdown on the detail page. Header row +
// exactly one record, CRLF-separated per RFC-4180 (sec 2.1). Mirrors the bulk
// CSV's columns + quoting exactly because both call csvRow / CSV_HEADERS.
export function toCsv(s: ShotExportInput): string {
  return [CSV_HEADERS.join(","), csvRow(s)].join("\r\n");
}

// --- Shared export-format catalogue (single + bulk surfaces) --------------
// The shot-detail "copy as ..." trio (components/CopyExportButtons.tsx) and
// the /shots bulk "Copy ..." trio (components/BulkExportButtons.tsx) must
// expose the SAME three formats in the SAME order so the two surfaces can't
// drift (F86). This is the single source of truth for the format list + its
// labels; both components render their buttons by mapping over it, so adding
// a fourth format here lights it up on both surfaces at once.
export type ExportFormatKey = "json" | "markdown" | "csv";

export type ExportFormatMeta = {
  // Stable lowercase key used to dispatch the single-shot serializer
  // (toJson / toMarkdown / toCsv).
  key: ExportFormatKey;
  // Full noun. Doubles as the single-shot button label, the bulk-dispatch
  // key, and the toast noun ("Copied ... as JSON"). The capitalisation lines
  // up with the bulk serializers' format union ("JSON" | "Markdown" | "CSV").
  noun: "JSON" | "Markdown" | "CSV";
  // Compact label for the denser bulk button ("Copy MD" vs "Copy Markdown").
  short: string;
};

export const EXPORT_FORMATS: readonly ExportFormatMeta[] = [
  { key: "json", noun: "JSON", short: "JSON" },
  { key: "markdown", noun: "Markdown", short: "MD" },
  { key: "csv", noun: "CSV", short: "CSV" },
] as const;

// Look up a format's metadata by its lowercase key. Returns undefined for an
// unknown key so a caller can guard rather than crash.
export function exportFormatByKey(
  key: string,
): ExportFormatMeta | undefined {
  return EXPORT_FORMATS.find((f) => f.key === key);
}

// --- List-row -> export shape (shared table + grid) -----------------------
// The /shots list renders the same rows in three layouts (table, compact,
// grid) and every one can offer the per-row "Copy as ..." menu (F97/F109).
// Each layout previously hand-built the ShotExportInput from its row inline,
// which risked the surfaces drifting (the grid forgetting `source`, say). This
// is the single mapping from a list row to the export shape so all three
// layouts feed RowExportMenu byte-identical data. The row carries fewer fields
// than the detail record (no distribution / ocr_text / rationale), which is
// fine -- the serializers omit empty slots.

// The minimal list-row fields the export shape needs. A superset row (the
// page's full Row type) satisfies this structurally.
export type ShotRowLike = {
  id: string;
  filename: string;
  primary_category: string;
  confidence: number;
  created_at?: string;
  elapsed_ms?: number | null;
  source?: string | null;
  label?: string | null;
  tags?: string[];
};

// Map a list row to the export-input shape. Optional fields are normalised to
// null / [] so the result is stable regardless of which optionals the row
// happened to carry -- the table and grid get the exact same object.
export function shotRowToExportInput(r: ShotRowLike): ShotExportInput {
  return {
    id: r.id,
    filename: r.filename,
    created_at: r.created_at,
    primary_category: r.primary_category,
    confidence: r.confidence,
    elapsed_ms: r.elapsed_ms ?? null,
    source: r.source ?? null,
    label: r.label ?? null,
    tags: r.tags ?? [],
  };
}
