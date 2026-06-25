// View-mode persistence + resolution for the shots list. The /shots page
// can render as a dense table (the default, with bulk-select / compare /
// pin affordances), a thumbnail-style card grid (scannable, OCR-forward),
// or a compact table (same columns, tighter rows for power users scanning
// hundreds of rows). Keeping the parse / cycle / label logic here -- pure,
// DOM-free -- mirrors lib/theme.ts so it's unit-testable and the toggle
// component stays a thin renderer.

export type ShotsViewMode = "table" | "grid" | "compact";

export const SHOTS_VIEW_STORAGE_KEY = "shotclassify.shots.view";

export const SHOTS_VIEW_MODES: ShotsViewMode[] = ["table", "grid", "compact"];

// Coerce a persisted / URL value into a known mode. Anything unrecognised
// falls back to "table" so a corrupted or future-schema value never leaves
// the list unrenderable.
export function parseViewMode(raw: string | null | undefined): ShotsViewMode {
  if (typeof raw !== "string") return "table";
  const t = raw.trim().toLowerCase();
  if ((SHOTS_VIEW_MODES as string[]).includes(t)) return t as ShotsViewMode;
  return "table";
}

// Cycle order for a single toggle button: table -> grid -> compact -> table.
export function nextViewMode(mode: ShotsViewMode): ShotsViewMode {
  if (mode === "table") return "grid";
  if (mode === "grid") return "compact";
  return "table";
}

// Human label for the active mode -- used in the toggle's aria-label / title.
export function labelForViewMode(mode: ShotsViewMode): string {
  if (mode === "grid") return "Grid";
  if (mode === "compact") return "Compact";
  return "Table";
}

// Whether the mode renders the <table> element (table + compact do; grid
// does not). Lets the page branch its render without re-deriving the rule.
export function isTabular(mode: ShotsViewMode): boolean {
  return mode === "table" || mode === "compact";
}

// Whether the mode should use the tighter row chrome. Only "compact" does;
// the page composes this into a CSS class on the table.
export function isCompact(mode: ShotsViewMode): boolean {
  return mode === "compact";
}
