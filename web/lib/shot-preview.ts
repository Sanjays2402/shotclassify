// Pure view-model for the /shots per-row inline preview drawer (F84). Clicking
// a table row's expand chevron opens a drawer UNDER that row showing a quick
// look -- an OCR snippet, the top few confidence classes as mini bars, and the
// classifier rationale -- without leaving the list. The drawer lazily fetches
// the shot's detail record (the list row carries only summary fields), and
// this module turns that raw record into the exact display shape the component
// renders. Framework-free so the trimming / sorting / fallback logic is
// unit-testable without a DOM and the component stays a thin renderer.
//
// Mirrors the detail page's own record shape (app/shots/[id]/page.tsx `Detail`)
// but only the slots the preview needs, and normalises the two places OCR text
// and rationale can live (top-level vs nested `ocr` / `classification`).

// The subset of the detail record the preview consumes. A superset record (the
// full detail `Detail` type) satisfies this structurally.
export type ShotPreviewRecord = {
  primary_category?: string | null;
  confidence?: number | null;
  ocr_text?: string | null;
  ocr?: { text?: string | null } | null;
  classification?: {
    confidences?: { category: string; score: number }[] | null;
    rationale?: string | null;
  } | null;
};

// One confidence row in the mini distribution: a class plus its 0..1 score and
// a pre-clamped 0..100 percent for the bar width.
export type PreviewConfidence = {
  category: string;
  score: number;
  pct: number;
};

export type ShotPreviewModel = {
  // Trimmed OCR snippet (single-line, capped) or null when there's no text.
  ocrSnippet: string | null;
  // True when the OCR text was longer than the snippet cap (so the UI can show
  // a "…" / "view full" affordance).
  ocrTruncated: boolean;
  // Top-N confidence rows, highest score first. Empty when the record carries
  // no distribution.
  topConfidences: PreviewConfidence[];
  // Trimmed rationale or null.
  rationale: string | null;
};

// Clamp a raw 0..1 score into a stable 0..100 percentage (one decimal). A stray
// >1 or NaN score can never produce a bar wider than the track.
function pct(score: number): number {
  if (!Number.isFinite(score)) return 0;
  const clamped = Math.max(0, Math.min(1, score));
  return Number((clamped * 100).toFixed(1));
}

// Collapse internal whitespace / newlines to single spaces so a multi-line OCR
// blob renders as one tidy snippet line, then trim the ends.
function flatten(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

// Build the OCR snippet from whichever slot carries the text (nested `ocr.text`
// preferred -- it's the structured OCR result -- then the flat `ocr_text`).
// Returns null when neither holds non-empty text. `max` caps the snippet length;
// truncation is reported so the UI can hint there's more.
export function previewOcr(
  rec: ShotPreviewRecord,
  max = 240,
): { snippet: string | null; truncated: boolean } {
  // Flatten each candidate first, then take the first that's actually non-empty
  // -- a nested ocr.text of pure whitespace must fall through to the flat field
  // rather than win on truthiness and flatten away to nothing.
  const nested = typeof rec.ocr?.text === "string" ? flatten(rec.ocr.text) : "";
  const flatField = typeof rec.ocr_text === "string" ? flatten(rec.ocr_text) : "";
  const flat = nested || flatField;
  if (!flat) return { snippet: null, truncated: false };
  if (flat.length <= max) return { snippet: flat, truncated: false };
  // Cut on a word boundary near the cap so we don't slice mid-word.
  const slice = flat.slice(0, max);
  const lastSpace = slice.lastIndexOf(" ");
  const body = lastSpace > max * 0.6 ? slice.slice(0, lastSpace) : slice;
  return { snippet: `${body.trimEnd()}…`, truncated: true };
}

// Top-N confidence rows, highest first. Reads the nested classification
// distribution, drops malformed entries (non-string class / non-finite score),
// sorts descending, and caps at `limit`. The primary category + overall
// confidence are folded in as a synthetic row IF the distribution is absent but
// the summary fields are present, so a row with only summary data still shows
// its winning class.
export function previewConfidences(
  rec: ShotPreviewRecord,
  limit = 4,
): PreviewConfidence[] {
  const dist = rec.classification?.confidences;
  if (Array.isArray(dist) && dist.length > 0) {
    return dist
      .filter(
        (d) =>
          d &&
          typeof d.category === "string" &&
          d.category.trim() &&
          Number.isFinite(d.score),
      )
      .map((d) => ({ category: d.category, score: d.score, pct: pct(d.score) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, Math.max(0, limit));
  }
  // Fallback: a single synthetic row from the summary fields.
  if (
    typeof rec.primary_category === "string" &&
    rec.primary_category.trim() &&
    typeof rec.confidence === "number" &&
    Number.isFinite(rec.confidence)
  ) {
    return [
      {
        category: rec.primary_category,
        score: rec.confidence,
        pct: pct(rec.confidence),
      },
    ];
  }
  return [];
}

// The FULL OCR text for the drawer's "copy OCR" button (F124). The drawer
// shows a truncated, whitespace-flattened SNIPPET (previewOcr) so the row
// stays compact, but a copy should hand over everything the shot captured.
// This returns the complete OCR text from whichever slot holds it (nested
// `ocr.text` preferred, then flat `ocr_text`), with only the leading/trailing
// whitespace trimmed -- internal newlines are PRESERVED so the copied text
// keeps the transcript's line structure (unlike the snippet, which collapses
// it to one line for display). null when neither slot carries real text, so
// the button can hide itself rather than copy an empty string.
export function previewOcrFull(rec: ShotPreviewRecord): string | null {
  const nested = typeof rec.ocr?.text === "string" ? rec.ocr.text : "";
  const flatField = typeof rec.ocr_text === "string" ? rec.ocr_text : "";
  // Mirror previewOcr's slot preference: a nested value that's only
  // whitespace must fall through to the flat field rather than win and trim
  // away to nothing. flatten() collapses for the emptiness test only.
  const nestedReal = flatten(nested) ? nested : "";
  const flatReal = flatten(flatField) ? flatField : "";
  const raw = nestedReal || flatReal;
  const trimmed = raw.trim();
  return trimmed ? trimmed : null;
}

// Trim the classifier rationale; null when absent / blank.
export function previewRationale(rec: ShotPreviewRecord): string | null {
  const r = rec.classification?.rationale;
  if (typeof r === "string" && r.trim()) return r.trim();
  return null;
}

// Top-level convenience -- assemble the full preview model from a raw record.
export function buildShotPreview(
  rec: ShotPreviewRecord,
  opts: { ocrMax?: number; confLimit?: number } = {},
): ShotPreviewModel {
  const { snippet, truncated } = previewOcr(rec, opts.ocrMax);
  return {
    ocrSnippet: snippet,
    ocrTruncated: truncated,
    topConfidences: previewConfidences(rec, opts.confLimit),
    rationale: previewRationale(rec),
  };
}

// True when the assembled model has anything worth showing. Lets the drawer
// render a tidy "nothing captured" line instead of three empty sections.
export function previewHasContent(m: ShotPreviewModel): boolean {
  return (
    m.ocrSnippet !== null ||
    m.topConfidences.length > 0 ||
    m.rationale !== null
  );
}
