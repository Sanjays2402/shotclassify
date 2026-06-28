// Set-math for the /shots "expand / collapse all previews" toolbar control
// (F119). The page tracks which rows have their inline preview drawer open
// (F84) as a Set<string> of shot ids. This control flips every CURRENTLY
// VISIBLE row's preview at once. Keeping the math here -- pure, DOM-free --
// mirrors the detail-rail Expand/Collapse-all helpers (F82) so the predicate +
// transforms are unit-testable and the page stays a thin caller.
//
// Scope note: the expanded Set can hold ids from other pages (it persists
// across pagination), so every transform operates ONLY on the visible ids and
// PRESERVES any off-page expanded ids untouched -- expanding/collapsing "all"
// on page 2 never silently closes a preview you left open on page 1.

// Normalise the visible-id list: drop non-strings / blanks and de-dupe, so a
// malformed row list can't skew the counts or predicates.
function cleanIds(ids: readonly string[]): string[] {
  if (!Array.isArray(ids)) return [];
  const seen = new Set<string>();
  for (const id of ids) {
    if (typeof id === "string" && id) seen.add(id);
  }
  return [...seen];
}

// How many of the visible rows currently have their preview open. Counts only
// ids that appear in BOTH the visible list and the expanded set.
export function expandedOnPageCount(
  expanded: Set<string>,
  ids: readonly string[],
): number {
  return cleanIds(ids).reduce(
    (n, id) => (expanded.has(id) ? n + 1 : n),
    0,
  );
}

// True when EVERY visible row's preview is open -- the "Collapse all" state.
// False when there are no visible rows (there's nothing to have all-of).
export function allPreviewsExpanded(
  expanded: Set<string>,
  ids: readonly string[],
): boolean {
  const clean = cleanIds(ids);
  if (clean.length === 0) return false;
  return clean.every((id) => expanded.has(id));
}

// True when AT LEAST ONE visible row's preview is open. Lets the control
// decide whether a "Collapse all" action would do anything.
export function anyPreviewsExpanded(
  expanded: Set<string>,
  ids: readonly string[],
): boolean {
  return cleanIds(ids).some((id) => expanded.has(id));
}

// A NEW expanded set with every visible id added (off-page ids preserved).
// Immutable so React sees a changed reference.
export function expandAllPreviews(
  expanded: Set<string>,
  ids: readonly string[],
): Set<string> {
  const next = new Set(expanded);
  for (const id of cleanIds(ids)) next.add(id);
  return next;
}

// A NEW expanded set with every visible id removed (off-page ids preserved).
export function collapseAllPreviews(
  expanded: Set<string>,
  ids: readonly string[],
): Set<string> {
  const next = new Set(expanded);
  for (const id of cleanIds(ids)) next.delete(id);
  return next;
}

// The label for the single toggle button. When every visible preview is open,
// the useful action is to collapse them; otherwise, expand them all. Returns
// null when there are no visible rows so the control can hide itself rather
// than offer a no-op.
export function previewToggleAllLabel(
  expanded: Set<string>,
  ids: readonly string[],
): "Expand all previews" | "Collapse all previews" | null {
  if (cleanIds(ids).length === 0) return null;
  return allPreviewsExpanded(expanded, ids)
    ? "Collapse all previews"
    : "Expand all previews";
}
