// Facet parsing for the command palette. Lets a user type structured
// filters inline -- `class:receipt`, `>90%`, `tag:urgent` -- and have the
// shot search narrow by category / confidence / tag without leaving the
// modal. Pure + DOM-free so it's unit-tested directly; the CommandPalette
// component feeds the residual free text to /api/history alongside the
// parsed facets.

import { CATEGORIES, SHORT, type Category } from "./categories";

export type PaletteFacets = {
  // Resolved category filter, or undefined when none was typed.
  category?: Category;
  // Confidence floor as a 0..1 fraction (from `>90%` / `>=0.8` / `conf:80`).
  minConf?: number;
  // Confidence ceiling as a 0..1 fraction (from `<50%`).
  maxConf?: number;
  // Tag filter (lowercased, from `tag:foo` / `#foo`).
  tag?: string;
  // Whatever's left after stripping the facet tokens -- the free-text query.
  text: string;
};

// Build a lookup from the various ways a user might name a category to its
// canonical enum value. Accepts the enum value itself ("receipt",
// "code_snippet"), the short broadcast label ("code", "error"), and a few
// friendly aliases.
const CATEGORY_ALIASES: Record<string, Category> = (() => {
  const map: Record<string, Category> = {};
  for (const c of CATEGORIES) {
    map[c] = c;
    map[SHORT[c].toLowerCase()] = c;
  }
  // Hand aliases for the longer enum values + common shorthands.
  Object.assign(map, {
    code: "code_snippet",
    snippet: "code_snippet",
    error: "error_stacktrace",
    stacktrace: "error_stacktrace",
    trace: "error_stacktrace",
    chat: "chat_screenshot",
    screenshot: "chat_screenshot",
    ui: "ui_mockup",
    mockup: "ui_mockup",
    doc: "document",
  } as Record<string, Category>);
  return map;
})();

// Resolve a raw category token to a canonical Category, or undefined if it
// doesn't name a known class.
export function resolveCategory(raw: string): Category | undefined {
  const key = raw.trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (key in CATEGORY_ALIASES) return CATEGORY_ALIASES[key];
  // Try the un-underscored form too ("code snippet" -> "code").
  const collapsed = raw.trim().toLowerCase().replace(/[\s_-]+/g, "");
  for (const [alias, cat] of Object.entries(CATEGORY_ALIASES)) {
    if (alias.replace(/_/g, "") === collapsed) return cat;
  }
  return undefined;
}

// Coerce a confidence token's numeric part to a 0..1 fraction. Accepts a
// bare percent ("90" -> 0.9, "90%" -> 0.9) or an already-fractional value
// ("0.9" -> 0.9). Returns undefined for nonsense / out-of-range input.
export function parseConfValue(raw: string): number | undefined {
  const s = raw.trim().replace(/%$/, "");
  if (!/^\d*\.?\d+$/.test(s)) return undefined;
  let n = Number(s);
  if (!Number.isFinite(n)) return undefined;
  // A value > 1 is read as a percent.
  if (n > 1) n = n / 100;
  if (n < 0 || n > 1) return undefined;
  return n;
}

// Parse a full palette query into facets + residual free text. Recognised
// tokens (any order, space-separated):
//   class:<cat>  category:<cat>  in:<cat>
//   tag:<name>   #<name>
//   >NN%  >=NN%  <NN%  <=NN%   (confidence bounds)
//   conf:NN  confidence:NN     (treated as a floor)
// Unknown tokens stay in the residual text.
export function parseFacets(query: string): PaletteFacets {
  const facets: PaletteFacets = { text: "" };
  const residual: string[] = [];
  const tokens = query.split(/\s+/).filter(Boolean);

  for (const tok of tokens) {
    const lower = tok.toLowerCase();

    // class: / category: / in:
    const catMatch = /^(?:class|category|in):(.+)$/.exec(lower);
    if (catMatch) {
      const cat = resolveCategory(catMatch[1]);
      if (cat) {
        facets.category = cat;
        continue;
      }
      // Unresolved -> drop the prefix, keep the value as search text.
      residual.push(catMatch[1]);
      continue;
    }

    // tag: / #tag
    const tagMatch = /^(?:tag:|#)(.+)$/.exec(lower);
    if (tagMatch && tagMatch[1]) {
      facets.tag = tagMatch[1].toLowerCase().slice(0, 32);
      continue;
    }

    // conf: / confidence: -> floor
    const confKw = /^(?:conf|confidence):(.+)$/.exec(lower);
    if (confKw) {
      const v = parseConfValue(confKw[1]);
      if (v != null) {
        facets.minConf = v;
        continue;
      }
      residual.push(tok);
      continue;
    }

    // >NN% / >=NN% / <NN% / <=NN%
    const cmp = /^(>=|<=|>|<)\s*(\d*\.?\d+%?)$/.exec(lower);
    if (cmp) {
      const v = parseConfValue(cmp[2]);
      if (v != null) {
        if (cmp[1].startsWith(">")) facets.minConf = v;
        else facets.maxConf = v;
        continue;
      }
    }

    residual.push(tok);
  }

  facets.text = residual.join(" ").trim();
  return facets;
}

// True when the parse produced at least one structured facet (so the UI can
// show a "filtering by ..." affordance vs a plain text search).
export function hasFacets(f: PaletteFacets): boolean {
  return (
    f.category !== undefined ||
    f.minConf !== undefined ||
    f.maxConf !== undefined ||
    f.tag !== undefined
  );
}

// Build the /api/history query params from parsed facets + a result limit.
export function facetsToHistoryParams(
  f: PaletteFacets,
  limit = 8,
): {
  limit: number;
  q?: string;
  category?: string;
  tag?: string;
  min_conf?: number;
  max_conf?: number;
} {
  return {
    limit,
    q: f.text || undefined,
    category: f.category,
    tag: f.tag,
    min_conf: f.minConf,
    max_conf: f.maxConf,
  };
}

// A short human label for the active facets, used in the palette's
// filter-pill row. Returns "" when nothing's filtered.
export function describeFacets(f: PaletteFacets): string {
  const parts: string[] = [];
  if (f.category) parts.push(`class ${SHORT[f.category].toLowerCase()}`);
  if (f.minConf !== undefined) parts.push(`>=${Math.round(f.minConf * 100)}%`);
  if (f.maxConf !== undefined) parts.push(`<=${Math.round(f.maxConf * 100)}%`);
  if (f.tag) parts.push(`#${f.tag}`);
  return parts.join(" · ");
}
