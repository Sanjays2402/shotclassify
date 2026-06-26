// Persistence + validation for the /shots page-size selector (F51). The
// shots list lets you page through history at 25 / 50 / 100 / 200 rows, but
// historically always reopened on 50 -- a return visit to a dense workspace
// had to re-pick 200 every time. This module mirrors lib/stats-window.ts and
// lib/view-mode.ts: a tiny, DOM-free parse/serialize pair plus a known-sizes
// list, so a return visit reopens on the density you last used. The page
// reads it on mount and writes it whenever the selector changes.

// The page size is the same `limit` value the page already feeds to the
// history endpoint -- no second source of truth to keep in sync.
export type ShotsPageSize = 25 | 50 | 100 | 200;

export const SHOTS_PAGE_SIZE_STORAGE_KEY = "shotclassify.shots.pagesize";

// The default the page opens on the very first visit (no stored value).
export const SHOTS_PAGE_SIZE_DEFAULT: ShotsPageSize = 50;

// Every page size the selector offers. Order matches the on-screen options.
export const SHOTS_PAGE_SIZES: ShotsPageSize[] = [25, 50, 100, 200];

function isKnownSize(n: number): n is ShotsPageSize {
  return (SHOTS_PAGE_SIZES as number[]).includes(n);
}

// Coerce a persisted / selector value into a known page size. Accepts a
// number or a numeric string (localStorage only stores strings, and a
// <select> onChange hands back a string too). Anything unrecognised -- a
// corrupt blob, a future-schema value, a non-numeric string -- falls back to
// the default so the page always renders a valid size.
export function parseShotsPageSize(
  raw: string | number | null | undefined,
): ShotsPageSize {
  if (typeof raw === "number") {
    return isKnownSize(raw) ? raw : SHOTS_PAGE_SIZE_DEFAULT;
  }
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw.trim());
    if (Number.isFinite(n) && isKnownSize(n)) return n;
  }
  return SHOTS_PAGE_SIZE_DEFAULT;
}

// Serialize back to the string localStorage stores. Symmetric with
// parseShotsPageSize(serializeShotsPageSize(n)).
export function serializeShotsPageSize(n: ShotsPageSize): string {
  return String(n);
}

// Short human label for a size -- used in the selector options / aria.
export function labelForShotsPageSize(n: ShotsPageSize): string {
  return `${n} / page`;
}

// --- Browser wrappers (no-throw) -----------------------------------------

// Read the persisted page size. Returns the default on SSR / blocked storage
// / a corrupt value. Safe to call from a mount effect.
export function readShotsPageSize(): ShotsPageSize {
  if (typeof window === "undefined") return SHOTS_PAGE_SIZE_DEFAULT;
  try {
    return parseShotsPageSize(
      window.localStorage.getItem(SHOTS_PAGE_SIZE_STORAGE_KEY),
    );
  } catch {
    return SHOTS_PAGE_SIZE_DEFAULT;
  }
}

// Persist the selected page size. No-throw: swallows quota / privacy-mode
// errors so a write failure never breaks the selector.
export function writeShotsPageSize(n: ShotsPageSize): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      SHOTS_PAGE_SIZE_STORAGE_KEY,
      serializeShotsPageSize(n),
    );
  } catch {
    // Ignore -- the in-memory selection still works for this session.
  }
}
