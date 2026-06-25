// Recently-viewed-shots MRU (most-recently-used) ring for the command
// palette (F32). When the palette opens with an empty query we show the last
// few shots the user actually looked at, above the nav results -- a faster
// path back to a record than re-searching for it. The shot-detail page
// records a visit on load; the palette reads the list.
//
// Pure + DOM-free so the ring math (push / dedupe / cap / parse) is
// unit-testable. The thin browser wrappers at the bottom touch localStorage
// behind try/catch so privacy-mode / quota errors never throw into render.

// One remembered shot. We store just enough to render a palette row without
// re-fetching: id (for the link), a display label, and the class chip.
export type RecentShot = {
  id: string;
  // What to show -- the user's label, else the filename, else the id.
  label: string;
  // primary_category, so the row can render a class eyebrow. Optional because
  // an older stored entry (or a partial record) may lack it.
  category?: string;
  // Epoch ms of the visit, newest-first ordering key.
  viewedAt: number;
};

export const RECENT_SHOTS_STORAGE_KEY = "shotclassify.recent.shots";

// How many we keep. Small -- this is a "jump back to what I was just looking
// at" affordance, not a history page.
export const RECENT_SHOTS_MAX = 6;

// Push a freshly-viewed shot to the front of the ring. Pure: returns a NEW
// array. An existing entry with the same id is removed first so the shot
// moves to the front (MRU) rather than duplicating, and its metadata is
// refreshed to the latest visit. Entries beyond the cap are dropped from the
// tail. A blank id is rejected (returns the list unchanged).
export function pushRecentShot(
  list: readonly RecentShot[],
  shot: RecentShot,
  max = RECENT_SHOTS_MAX,
): RecentShot[] {
  const id = typeof shot.id === "string" ? shot.id.trim() : "";
  if (!id) return Array.isArray(list) ? [...list] : [];
  const rest = (Array.isArray(list) ? list : []).filter((s) => s.id !== id);
  const entry: RecentShot = {
    id,
    label: shot.label && shot.label.trim() ? shot.label.trim() : id,
    category: shot.category,
    viewedAt: Number.isFinite(shot.viewedAt) ? shot.viewedAt : Date.now(),
  };
  return [entry, ...rest].slice(0, Math.max(0, max));
}

// Coerce an unknown parsed-JSON blob into a clean, ordered RecentShot[].
// Drops malformed entries, de-dupes by id (first-seen wins -- the array is
// already newest-first), sorts by viewedAt descending defensively in case a
// hand-edited blob is out of order, and caps the length.
export function parseRecentShots(
  raw: unknown,
  max = RECENT_SHOTS_MAX,
): RecentShot[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: RecentShot[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const r = item as Record<string, unknown>;
    const id = typeof r.id === "string" ? r.id.trim() : "";
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({
      id,
      label:
        typeof r.label === "string" && r.label.trim() ? r.label.trim() : id,
      category: typeof r.category === "string" ? r.category : undefined,
      viewedAt: Number.isFinite(r.viewedAt as number)
        ? (r.viewedAt as number)
        : 0,
    });
  }
  out.sort((a, b) => b.viewedAt - a.viewedAt);
  return out.slice(0, Math.max(0, max));
}

// Serialise back to a JSON string for storage. Symmetric with
// parseRecentShots(JSON.parse(...)).
export function serializeRecentShots(list: readonly RecentShot[]): string {
  return JSON.stringify(Array.isArray(list) ? list : []);
}

// --- Browser wrappers (no-throw) -----------------------------------------

// Read the ring from localStorage. Returns [] on any failure (SSR, blocked
// storage, corrupt JSON).
export function readRecentShots(max = RECENT_SHOTS_MAX): RecentShot[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_SHOTS_STORAGE_KEY);
    if (!raw) return [];
    return parseRecentShots(JSON.parse(raw), max);
  } catch {
    return [];
  }
}

// Record a visit: read, push, write back. Returns the updated list (also []
// on failure). Safe to call from a detail-page effect on every mount.
export function recordRecentShot(
  shot: Omit<RecentShot, "viewedAt"> & { viewedAt?: number },
  max = RECENT_SHOTS_MAX,
): RecentShot[] {
  if (typeof window === "undefined") return [];
  try {
    const cur = readRecentShots(max);
    const next = pushRecentShot(
      cur,
      { ...shot, viewedAt: shot.viewedAt ?? Date.now() },
      max,
    );
    window.localStorage.setItem(
      RECENT_SHOTS_STORAGE_KEY,
      serializeRecentShots(next),
    );
    return next;
  } catch {
    return [];
  }
}
