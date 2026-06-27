// Pure helpers for the shots-table filter breadcrumb. Given the active
// filter state from /shots, produce an ordered list of removable "chips"
// each describing one active constraint plus the key needed to clear just
// that one. Keeping the label-building + clear logic here (framework-free)
// makes it unit-testable and lets the breadcrumb component stay a thin
// renderer. Pairs with describeFilters() in empty-state.ts (which builds a
// single prose summary) -- this module is the structured, individually
// removable version.

import { LONG, type Category } from "./categories";

// The slice of /shots state that actually constrains the result set. View
// options (sort, page size) are intentionally excluded -- the breadcrumb is
// about "what's narrowing my results", not "how am I viewing them".
export type ShotFilterState = {
  category?: string | null;
  q?: string | null;
  tag?: string | null;
  // Confidence floor as a whole percent (0..100), matching the /shots slider.
  minConfPct?: number | null;
  since?: string | null; // yyyy-mm-dd
  until?: string | null; // yyyy-mm-dd
  pinnedOnly?: boolean;
};

// Stable identifiers for each clearable filter. The component maps these
// back to the page's individual setters.
export type FilterKey =
  | "category"
  | "q"
  | "tag"
  | "minConf"
  | "since"
  | "until"
  | "pinned";

export type FilterChip = {
  key: FilterKey;
  // Full human-readable label, e.g. `Class: Receipt`.
  label: string;
  // Short eyebrow shown before the value, e.g. `Class`. Lets the renderer
  // style the key + value differently.
  field: string;
  // The value portion, e.g. `Receipt`. Empty for boolean toggles.
  value: string;
};

// Trim a long search string for display so the chip never blows out the row.
function truncate(s: string, max = 28): string {
  const t = s.trim();
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

// True when a confidence floor is actually constraining (a 0% floor is the
// no-op default the slider starts at).
function hasConfFloor(p: number | null | undefined): p is number {
  return typeof p === "number" && Number.isFinite(p) && p > 0;
}

// Build the ordered chip list. Order is deliberate -- class first (the
// coarsest cut), then text search, tag, confidence, date range, pinned --
// so the breadcrumb reads the way a user would describe their filter.
export function activeFilterChips(f: ShotFilterState): FilterChip[] {
  const chips: FilterChip[] = [];

  if (typeof f.category === "string" && f.category.trim()) {
    const cat = f.category.trim() as Category;
    const value = LONG[cat] ?? f.category.trim();
    chips.push({ key: "category", field: "Class", value, label: `Class: ${value}` });
  }

  if (typeof f.q === "string" && f.q.trim()) {
    const value = `"${truncate(f.q)}"`;
    chips.push({ key: "q", field: "Search", value, label: `Search: ${value}` });
  }

  if (typeof f.tag === "string" && f.tag.trim()) {
    const value = `#${f.tag.trim()}`;
    chips.push({ key: "tag", field: "Tag", value, label: `Tag: ${value}` });
  }

  if (hasConfFloor(f.minConfPct)) {
    const value = `≥${Math.round(f.minConfPct)}%`;
    chips.push({ key: "minConf", field: "Confidence", value, label: `Confidence: ${value}` });
  }

  if (typeof f.since === "string" && f.since.trim()) {
    chips.push({ key: "since", field: "From", value: f.since.trim(), label: `From: ${f.since.trim()}` });
  }

  if (typeof f.until === "string" && f.until.trim()) {
    chips.push({ key: "until", field: "Until", value: f.until.trim(), label: `Until: ${f.until.trim()}` });
  }

  if (f.pinnedOnly === true) {
    chips.push({ key: "pinned", field: "Pinned", value: "only", label: "Pinned only" });
  }

  return chips;
}

// How many filters are currently active. Cheap convenience for the renderer
// (e.g. only show the breadcrumb + "Clear all" when count > 0).
export function countActiveFilters(f: ShotFilterState): number {
  return activeFilterChips(f).length;
}

// A compact "3 filters" / "1 filter" pill label for the toolbar (F91). When
// the toolbar is scrolled or the breadcrumb is off-screen, this pill signals
// at a glance that the list is narrowed. Returns null at zero so the caller
// renders nothing (no inert "0 filters" noise). Singular/plural aware.
export function filterCountLabel(f: ShotFilterState): string | null {
  const n = countActiveFilters(f);
  if (n <= 0) return null;
  return `${n} filter${n === 1 ? "" : "s"}`;
}

// Return a copy of the filter state with a single filter reset to its
// inert default. Pure -- the component can apply the result or, more
// commonly, route the cleared key to the matching individual setter.
export function clearFilter(f: ShotFilterState, key: FilterKey): ShotFilterState {
  const next: ShotFilterState = { ...f };
  switch (key) {
    case "category":
      next.category = "";
      break;
    case "q":
      next.q = "";
      break;
    case "tag":
      next.tag = "";
      break;
    case "minConf":
      next.minConfPct = 0;
      break;
    case "since":
      next.since = "";
      break;
    case "until":
      next.until = "";
      break;
    case "pinned":
      next.pinnedOnly = false;
      break;
  }
  return next;
}

// Reset every constraint at once -- backs the breadcrumb's "Clear all"
// affordance. Returns a fully inert filter state.
export function clearAllFilters(f: ShotFilterState): ShotFilterState {
  return {
    ...f,
    category: "",
    q: "",
    tag: "",
    minConfPct: 0,
    since: "",
    until: "",
    pinnedOnly: false,
  };
}
