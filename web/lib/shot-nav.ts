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
};

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
  if (!id) return { index: -1, total, prevId: null, nextId: null };

  const index = ring.findIndex((s) => s && s.id === id);
  if (index < 0) return { index: -1, total, prevId: null, nextId: null };

  const prevId = index > 0 ? ring[index - 1].id : null;
  const nextId = index < total - 1 ? ring[index + 1].id : null;
  return { index, total, prevId, nextId };
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
