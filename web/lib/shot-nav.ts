// Pure prev/next navigation over the recently-viewed shots ring (F49). The
// command palette already surfaces the MRU ring (lib/recent-shots.ts); this
// lets the shot-detail header step through that same list with chevrons and
// `[` / `]` keys, so paging back through what you were just reviewing is one
// keypress -- no fetch, no list round-trip.
//
// DOM-free + framework-free so the neighbour math is unit-testable. The ring
// is newest-first; we treat "prev" as the NEWER neighbour (toward index 0,
// the left chevron) and "next" as the OLDER neighbour (toward the tail, the
// right chevron) so the chevrons read left=back-in-time-recent, matching the
// visual order the palette renders.

import type { RecentShot } from "./recent-shots";

export type ShotNeighbors = {
  // Zero-based position of the current shot in the ring, or -1 if absent.
  index: number;
  // Total entries in the ring.
  total: number;
  // The newer neighbour's id (index - 1), or null at the head / when absent.
  prevId: string | null;
  // The older neighbour's id (index + 1), or null at the tail / when absent.
  nextId: string | null;
  // A short, human-legible label for each neighbour so the chevrons can read
  // as "< RECEIPT" / "CODE >" without a hover (F62). null when there is no
  // neighbour on that side. Derived from the frozen ring snapshot, never a
  // fetch -- the labels are the ones the user actually browsed.
  prevLabel: string | null;
  nextLabel: string | null;
};

// How long a neighbour label may be before we trim it with an ellipsis. Kept
// short so the chevron pair stays compact in the detail header.
const NEIGHBOR_LABEL_MAX = 18;

// Build a compact display label for a neighbour from its ring entry. Prefers
// the stored label (the user's label / filename), falling back to a shortened
// id so there's always something to show. Trimmed + ellipsised to keep the
// header tidy. Exported for the component + its tests.
export function neighborLabel(shot: RecentShot | null | undefined): string | null {
  if (!shot) return null;
  const raw =
    typeof shot.label === "string" && shot.label.trim()
      ? shot.label.trim()
      : typeof shot.id === "string"
        ? shot.id.slice(0, 8)
        : "";
  if (!raw) return null;
  return raw.length > NEIGHBOR_LABEL_MAX
    ? `${raw.slice(0, NEIGHBOR_LABEL_MAX - 1)}\u2026`
    : raw;
}

// Locate `currentId` in the ring and report its neighbours. A shot the user
// navigated to directly (deep link, not via a prior visit) won't be in the
// ring yet -- index -1, both neighbours null -- so the caller hides the
// affordance rather than guessing. Defensive against a non-array list and a
// blank id.
export function neighborShots(
  list: readonly RecentShot[] | null | undefined,
  currentId: string | null | undefined,
): ShotNeighbors {
  const ring = Array.isArray(list) ? list : [];
  const total = ring.length;
  const id = typeof currentId === "string" ? currentId.trim() : "";
  if (!id)
    return {
      index: -1,
      total,
      prevId: null,
      nextId: null,
      prevLabel: null,
      nextLabel: null,
    };

  const index = ring.findIndex((s) => s && s.id === id);
  if (index < 0)
    return {
      index: -1,
      total,
      prevId: null,
      nextId: null,
      prevLabel: null,
      nextLabel: null,
    };

  const prev = index > 0 ? ring[index - 1] : null;
  const next = index < total - 1 ? ring[index + 1] : null;
  return {
    index,
    total,
    prevId: prev ? prev.id : null,
    nextId: next ? next.id : null,
    prevLabel: neighborLabel(prev),
    nextLabel: neighborLabel(next),
  };
}

// True when there's at least one neighbour to step to -- lets the page skip
// rendering the nav entirely (a single-entry ring, or a shot not in it).
export function hasShotNav(n: ShotNeighbors): boolean {
  return n.prevId !== null || n.nextId !== null;
}

// Human position label for the nav, e.g. "2 of 6". Returns "" when the
// current shot isn't in the ring so the caller renders no counter.
export function shotNavLabel(n: ShotNeighbors): string {
  if (n.index < 0 || n.total <= 0) return "";
  return `${n.index + 1} of ${n.total}`;
}
