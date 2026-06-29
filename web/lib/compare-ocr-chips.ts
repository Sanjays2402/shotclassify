// Pure OCR-stat chip helpers for the /compare shot panels (F171). Each shot's
// detail payload already carries an `ocr` block with a word_count and a
// mean_confidence, but the compare panel only rendered the raw OCR text in a
// <pre> -- the two numbers that say "how much text, how legible" were invisible.
// This module turns the raw ocr block into a tidy, formatted chip list the
// panel renders above the text, so you can eyeball "212 words, 91% legible"
// without counting. DOM-free so the formatting + guards are unit-testable; the
// component owns the chip markup.

// The minimal ocr shape the panel detail carries. All fields optional because
// a shot may have no OCR (a meme with no text) or a partial block.
export type OcrLike = {
  text?: string;
  word_count?: number;
  mean_confidence?: number;
};

export type OcrChip = {
  // Stable key for React + tests.
  key: "words" | "legibility";
  // Short uppercase eyebrow, e.g. "WORDS".
  label: string;
  // Formatted value, e.g. "212" or "91%".
  value: string;
  // For the legibility chip only: the 0..1 fraction so the component can tint
  // it via confColor. Undefined for the word-count chip (no tier).
  score?: number;
};

function isFiniteNum(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

// Derive a word count: prefer the payload's own count, else fall back to
// splitting the text on whitespace so a block that carried text but no count
// still reports a number. Returns null when neither is usable.
export function ocrWordCount(ocr: OcrLike | null | undefined): number | null {
  if (!ocr) return null;
  if (isFiniteNum(ocr.word_count) && ocr.word_count >= 0) {
    return Math.trunc(ocr.word_count);
  }
  if (typeof ocr.text === "string") {
    const trimmed = ocr.text.trim();
    if (trimmed === "") return 0;
    return trimmed.split(/\s+/).length;
  }
  return null;
}

// Clamp a mean confidence to a 0..1 fraction, or null when absent / invalid.
export function ocrMeanConfidence(ocr: OcrLike | null | undefined): number | null {
  if (!ocr || !isFiniteNum(ocr.mean_confidence)) return null;
  return Math.min(1, Math.max(0, ocr.mean_confidence));
}

// Build the chip list for a shot's OCR block. Returns [] when there's nothing
// worth showing (no count AND no confidence) so the panel hides the row
// entirely for image-only shots. A zero word count IS shown -- "0 words" is a
// meaningful fact, distinct from "no OCR ran".
export function ocrChips(ocr: OcrLike | null | undefined): OcrChip[] {
  const chips: OcrChip[] = [];
  const words = ocrWordCount(ocr);
  if (words !== null) {
    chips.push({
      key: "words",
      label: "Words",
      value: words.toLocaleString(),
    });
  }
  const conf = ocrMeanConfidence(ocr);
  if (conf !== null) {
    chips.push({
      key: "legibility",
      label: "Legibility",
      value: `${Math.round(conf * 100)}%`,
      score: conf,
    });
  }
  return chips;
}
