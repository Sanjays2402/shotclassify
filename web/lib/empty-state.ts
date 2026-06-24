// Pure helpers for the EmptyState component: given the active filter set
// from a list page, produce the title + body copy a user actually wants to
// read. Keeping this in a separate, framework-free module makes it
// unit-testable and lets every list view (shots / notifications / webhooks)
// share the wording without a giant switch statement.

export type ListFiltersForEmptyState = {
  q?: string | null;
  category?: string | null;
  tag?: string | null;
  // Confidence-floor as a 0..1 fraction (e.g. 0.7 for "70%+").
  min_conf?: number | null;
  // ISO date strings (yyyy-mm-dd is fine).
  since?: string | null;
  until?: string | null;
  // The "pinned only" / "unread only" toggle. Caller picks the verb.
  pinnedOnly?: boolean;
  unreadOnly?: boolean;
};

// Returns true when ANY of the filter slots are actively constraining the
// underlying list. A page that calls EmptyState with no filters should
// render the "first run" copy; with filters should render the "wider net"
// copy.
export function hasActiveFilters(f: ListFiltersForEmptyState): boolean {
  if (typeof f.q === "string" && f.q.trim().length > 0) return true;
  if (typeof f.category === "string" && f.category.trim().length > 0) return true;
  if (typeof f.tag === "string" && f.tag.trim().length > 0) return true;
  if (typeof f.min_conf === "number" && f.min_conf > 0) return true;
  if (typeof f.since === "string" && f.since.trim().length > 0) return true;
  if (typeof f.until === "string" && f.until.trim().length > 0) return true;
  if (f.pinnedOnly === true) return true;
  if (f.unreadOnly === true) return true;
  return false;
}

// Build a human-readable summary of the active filters for the empty-state
// body. Used when we want to remind the user what they had applied so the
// fix is obvious. Returns "" when nothing's filtered.
export function describeFilters(f: ListFiltersForEmptyState): string {
  const parts: string[] = [];
  if (typeof f.category === "string" && f.category.trim())
    parts.push(`class ${f.category.trim()}`);
  if (typeof f.q === "string" && f.q.trim())
    parts.push(`search "${f.q.trim().slice(0, 32)}${f.q.trim().length > 32 ? "…" : ""}"`);
  if (typeof f.tag === "string" && f.tag.trim())
    parts.push(`tag #${f.tag.trim()}`);
  if (typeof f.min_conf === "number" && f.min_conf > 0)
    parts.push(`>=${Math.round(f.min_conf * 100)}% confidence`);
  if (typeof f.since === "string" && f.since.trim() && typeof f.until === "string" && f.until.trim())
    parts.push(`between ${f.since} and ${f.until}`);
  else if (typeof f.since === "string" && f.since.trim())
    parts.push(`since ${f.since}`);
  else if (typeof f.until === "string" && f.until.trim())
    parts.push(`until ${f.until}`);
  if (f.pinnedOnly) parts.push("pinned only");
  if (f.unreadOnly) parts.push("unread only");
  return parts.join(" · ");
}

// Top-level convenience -- given the active filter set, produce title + body
// copy. Two flavours: with filters ("Nothing under that filter"), and the
// blank-slate first-run case.
export type EmptyCopy = { title: string; body: string };

export function emptyCopyForList(
  noun: string,
  f: ListFiltersForEmptyState,
): EmptyCopy {
  if (hasActiveFilters(f)) {
    const summary = describeFilters(f);
    return {
      title: `No ${noun} match that filter`,
      body: summary
        ? `Active: ${summary}. Try widening the search or clearing a filter.`
        : "Try widening the search or clearing a filter.",
    };
  }
  return {
    title: `No ${noun} yet`,
    body: `Once the service starts logging ${noun}, they'll show up here. Feed it a frame to get rolling.`,
  };
}
