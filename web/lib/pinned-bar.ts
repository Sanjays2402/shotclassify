// Pure helpers for the pinned-shots quick-bar on the Live page (F15). The
// home page already pulls recent history; this module distills the pinned
// subset into a small, stable, capped list the quick-bar can render so a
// user can jump straight back to their starred work without browsing all
// shots. DOM-free so the selection / sort / cap logic is unit-testable.

import type { Category } from "./categories";

// The minimal shape the quick-bar needs from a history record. The live
// feed's rows carry more, but we only read these.
export type PinnableShot = {
  id: string;
  filename: string;
  primary_category: Category;
  confidence: number;
  created_at: string;
  label?: string | null;
  pinned?: boolean;
};

export type PinnedQuickItem = {
  id: string;
  // The display name -- label when set and non-empty, else the filename,
  // else the id as a last resort so a card is never blank.
  name: string;
  primary_category: Category;
  confidence: number;
  created_at: string;
};

// Default number of pinned shots the bar shows before "+N more".
export const PINNED_BAR_DEFAULT_CAP = 12;

// Resolve the best display name for a record.
function displayName(s: PinnableShot): string {
  const label = typeof s.label === "string" ? s.label.trim() : "";
  if (label) return label;
  const file = typeof s.filename === "string" ? s.filename.trim() : "";
  if (file) return file;
  return s.id;
}

// Parse an ISO timestamp to epoch ms, or 0 when missing / unparseable so a
// record with a bad date sorts last rather than throwing.
function epoch(iso: string | null | undefined): number {
  if (typeof iso !== "string") return 0;
  const t = new Date(iso).getTime();
  return Number.isFinite(t) ? t : 0;
}

// Build the quick-bar item list from a recent-history array: keep only the
// pinned rows, newest first, de-duplicated by id, capped. Returns [] when
// nothing is pinned (the bar should then hide entirely).
export function pinnedQuickItems(
  shots: readonly PinnableShot[] | null | undefined,
  cap: number = PINNED_BAR_DEFAULT_CAP,
): PinnedQuickItem[] {
  if (!Array.isArray(shots) || shots.length === 0) return [];
  const seen = new Set<string>();
  const pinned = shots
    .filter((s) => s && s.pinned === true && typeof s.id === "string" && s.id.length > 0)
    .filter((s) => {
      if (seen.has(s.id)) return false;
      seen.add(s.id);
      return true;
    })
    .sort((a, b) => epoch(b.created_at) - epoch(a.created_at));

  const limit = Number.isFinite(cap) && cap > 0 ? Math.floor(cap) : PINNED_BAR_DEFAULT_CAP;
  return pinned.slice(0, limit).map((s) => ({
    id: s.id,
    name: displayName(s),
    primary_category: s.primary_category,
    confidence: s.confidence,
    created_at: s.created_at,
  }));
}

// Total pinned count (before the cap) -- drives the "+N more" affordance.
export function pinnedCount(
  shots: readonly PinnableShot[] | null | undefined,
): number {
  if (!Array.isArray(shots)) return 0;
  const seen = new Set<string>();
  let n = 0;
  for (const s of shots) {
    if (s && s.pinned === true && typeof s.id === "string" && s.id.length > 0 && !seen.has(s.id)) {
      seen.add(s.id);
      n++;
    }
  }
  return n;
}

// How many pinned shots are hidden beyond the cap (for the "+N more" label).
// Never negative.
export function pinnedOverflow(
  shots: readonly PinnableShot[] | null | undefined,
  cap: number = PINNED_BAR_DEFAULT_CAP,
): number {
  const total = pinnedCount(shots);
  const limit = Number.isFinite(cap) && cap > 0 ? Math.floor(cap) : PINNED_BAR_DEFAULT_CAP;
  return Math.max(0, total - limit);
}
