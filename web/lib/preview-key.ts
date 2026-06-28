// Resolve which row's preview the `o` keyboard shortcut should toggle (F118).
// Pressing `o` on /shots opens (or closes) one row's inline preview without
// the mouse. "Which row?" has a small, testable rule:
//   1. If keyboard focus is on (or inside) a known shot row, target THAT row --
//      the user is clearly working with it.
//   2. Otherwise fall back to the FIRST visible row, so `o` always does
//      something on a populated list even when focus is elsewhere (the filter
//      toolbar, say).
// Kept pure + DOM-free: the caller reads the focused shot id (from a
// data-attribute walk) and the visible id list, and this decides the target.
// Returns null only when there are no visible rows.

// The first visible row id, or null when the list is empty / malformed.
export function firstVisibleId(ids: readonly string[]): string | null {
  if (!Array.isArray(ids)) return null;
  for (const id of ids) {
    if (typeof id === "string" && id) return id;
  }
  return null;
}

// Pick the row whose preview `o` should toggle. `focusedId` is the shot id the
// DOM focus currently sits within (null when focus isn't on a row). We only
// honour a focused id that's actually in the visible list -- a stale focus
// (e.g. a row that just paged away) falls back to the first visible row rather
// than targeting something off-screen.
export function pickPreviewTarget(
  focusedId: string | null | undefined,
  ids: readonly string[],
): string | null {
  if (
    typeof focusedId === "string" &&
    focusedId &&
    Array.isArray(ids) &&
    ids.includes(focusedId)
  ) {
    return focusedId;
  }
  return firstVisibleId(ids);
}
