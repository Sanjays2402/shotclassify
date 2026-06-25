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
