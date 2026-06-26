// Pure parser for the /shots deep-link query string (F30). Several surfaces
// already link INTO the shots list pre-filtered -- the stats class-mix chips
// (`?category=receipt`), the pinned quick-bar's "View all" (`?pinned=true`),
// the category legend popover, the "All classes" grid -- but the page has
// historically ignored its own query params, so those links landed unfiltered.
// This module turns a URLSearchParams (or any {get(name)} shape) into a clean,
// validated slice of the page's initial filter state. DOM-free + framework-
// free so it's unit-testable; the page applies the result once on mount.

import { CATEGORIES, type Category } from "./categories";

export type ShotsSort = "new" | "old" | "conf_desc" | "conf_asc";

// The subset of /shots filter state a deep-link is allowed to seed. Every
// field is optional -- only the params actually present in the URL appear,
// so the caller can spread this over its defaults.
export type ShotsDeepLink = {
  category?: Category;
  q?: string;
  tag?: string;
  // Confidence floor as a whole percent (0..100), matching the slider.
  minConfPct?: number;
  since?: string; // yyyy-mm-dd
  until?: string;
  sort?: ShotsSort;
  pinnedOnly?: boolean;
};

// Anything with a string-or-null `get(name)` accessor. URLSearchParams and
// Next's ReadonlyURLSearchParams both satisfy this, and tests can pass a
// hand-rolled stub.
export type ParamSource = {
  get(name: string): string | null;
};

const VALID_SORTS: ReadonlySet<string> = new Set([
  "new",
  "old",
  "conf_desc",
  "conf_asc",
]);

// yyyy-mm-dd, the shape the date inputs emit. We validate the SHAPE only,
// not real-calendar validity -- an out-of-range day just yields an empty
// result set, which is harmless and self-correcting.
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

// Truthy-string set for the boolean `pinned` param. Accept the common
// affirmatives so both `?pinned=true` and `?pinned=1` work.
const TRUE_VALUES: ReadonlySet<string> = new Set(["true", "1", "yes", "on"]);

function isCategory(v: string): v is Category {
  return (CATEGORIES as string[]).includes(v);
}

// Parse a confidence param. Accepts a whole percent ("80") and clamps to
// 0..100; a fractional 0..1 form ("0.8") is upscaled to a percent so links
// built from either convention land correctly. Non-numeric -> undefined.
function parseConfPct(raw: string): number | undefined {
  const n = Number(raw);
  if (!Number.isFinite(n)) return undefined;
  // A value in (0,1] is treated as a fraction; >1 is already a percent.
  const pct = n > 0 && n <= 1 ? n * 100 : n;
  const clamped = Math.max(0, Math.min(100, Math.round(pct)));
  return clamped > 0 ? clamped : undefined; // a 0 floor is the inert default
}

// Build the deep-link filter slice from a param source. Unknown / malformed
// params are dropped silently so a hand-mangled URL never throws or wedges
// the page -- it just ignores the bits it can't trust.
export function parseShotsDeepLink(src: ParamSource | null | undefined): ShotsDeepLink {
  const out: ShotsDeepLink = {};
  if (!src || typeof src.get !== "function") return out;

  const category = src.get("category");
  if (category && isCategory(category.trim())) {
    out.category = category.trim() as Category;
  }

  const q = src.get("q");
  if (q && q.trim()) out.q = q.trim();

  const tag = src.get("tag");
  if (tag && tag.trim()) out.tag = tag.trim().toLowerCase().slice(0, 32);

  const conf = src.get("min_conf");
  if (conf != null && conf.trim()) {
    const pct = parseConfPct(conf.trim());
    if (pct != null) out.minConfPct = pct;
  }

  const since = src.get("since");
  if (since && ISO_DATE.test(since.trim())) out.since = since.trim();

  const until = src.get("until");
  if (until && ISO_DATE.test(until.trim())) out.until = until.trim();

  const sort = src.get("sort");
  if (sort && VALID_SORTS.has(sort.trim())) out.sort = sort.trim() as ShotsSort;

  const pinned = src.get("pinned");
  if (pinned != null && TRUE_VALUES.has(pinned.trim().toLowerCase())) {
    out.pinnedOnly = true;
  }

  return out;
}

// True when the deep-link actually seeds at least one filter. Lets the page
// skip the apply-on-mount work (and any history.replace) when the URL is bare.
export function hasDeepLink(link: ShotsDeepLink): boolean {
  return Object.keys(link).length > 0;
}

// --- Inverse: serialise the live filter state back INTO a deep-link (F47) ---
// The "Copy link to this view" button on /shots needs the mirror of the
// parser above: turn the page's current filter state into the same query
// string the parser consumes, so a shared URL reopens the list pre-filtered.
// Symmetric with parseShotsDeepLink -- only ACTIVE (non-default) filters are
// emitted, normalised the same way (tag lowercased+capped, conf as a whole
// percent, the inert sort="new" default and 0 conf floor omitted) so a
// round trip through parse(build(state)) is stable.
export type ShotsFilterState = {
  category?: Category | "" | null;
  q?: string | null;
  tag?: string | null;
  // Confidence floor as a whole percent (0..100). 0 is the inert default.
  minConfPct?: number | null;
  since?: string | null; // yyyy-mm-dd
  until?: string | null;
  sort?: ShotsSort | null;
  pinnedOnly?: boolean | null;
};

// Build the query string (WITHOUT a leading "?") for the current filter
// state. Returns "" when no filter is active, so the caller can link to a
// bare "/shots". Params are emitted in a stable, parser-friendly order.
export function buildShotsQuery(state: ShotsFilterState): string {
  const usp = new URLSearchParams();

  const category = typeof state.category === "string" ? state.category.trim() : "";
  if (category && isCategory(category)) usp.set("category", category);

  const q = typeof state.q === "string" ? state.q.trim() : "";
  if (q) usp.set("q", q);

  const tag =
    typeof state.tag === "string"
      ? state.tag.trim().toLowerCase().slice(0, 32)
      : "";
  if (tag) usp.set("tag", tag);

  // Only a meaningful floor (>0) is worth sharing; clamp to 0..100.
  if (typeof state.minConfPct === "number" && Number.isFinite(state.minConfPct)) {
    const pct = Math.max(0, Math.min(100, Math.round(state.minConfPct)));
    if (pct > 0) usp.set("min_conf", String(pct));
  }

  const since = typeof state.since === "string" ? state.since.trim() : "";
  if (since && ISO_DATE.test(since)) usp.set("since", since);

  const until = typeof state.until === "string" ? state.until.trim() : "";
  if (until && ISO_DATE.test(until)) usp.set("until", until);

  // "new" is the page default -- omit it so the link stays tight; any other
  // valid sort is explicit.
  const sort = typeof state.sort === "string" ? state.sort.trim() : "";
  if (sort && sort !== "new" && VALID_SORTS.has(sort)) usp.set("sort", sort);

  if (state.pinnedOnly === true) usp.set("pinned", "true");

  return usp.toString();
}

// Build the full deep-link path for the current filter state. Returns the
// bare base ("/shots") when no filter is active. Pass an absolute origin as
// `base` (e.g. `${location.origin}/shots`) to produce a shareable URL.
export function buildShotsDeepLink(
  state: ShotsFilterState,
  base = "/shots",
): string {
  const qs = buildShotsQuery(state);
  return qs ? `${base}?${qs}` : base;
}
