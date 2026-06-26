// Persistence + validation for the /stats time-window selector (F44). The
// Box-score page lets you scope every rollup to the last 24h / 7d / 30d, but
// historically always reopened on 24h. This module mirrors lib/view-mode.ts:
// a tiny, DOM-free parse/serialize pair plus a known-windows list, so a
// return visit can reopen on the window you last used. The page reads it on
// mount and writes it whenever the selector changes.

// The window is identified by its hour-count -- the same value the page
// already feeds to the aggregate endpoint -- so there's no second source of
// truth to keep in sync.
export type StatsWindowHours = 24 | 168 | 720;

export const STATS_WINDOW_STORAGE_KEY = "shotclassify.stats.window";

// The default the page opens on the very first visit (no stored value).
export const STATS_WINDOW_DEFAULT: StatsWindowHours = 24;

// Every window the selector offers. Order matches the on-screen buttons.
export const STATS_WINDOWS: StatsWindowHours[] = [24, 168, 720];

function isKnownWindow(n: number): n is StatsWindowHours {
  return (STATS_WINDOWS as number[]).includes(n);
}

// Coerce a persisted / URL value into a known window. Accepts a number or a
// numeric string (localStorage only stores strings). Anything unrecognised
// -- a corrupt blob, a future-schema value, a non-numeric string -- falls
// back to the default so the page always renders a valid window.
export function parseStatsWindow(
  raw: string | number | null | undefined,
): StatsWindowHours {
  if (typeof raw === "number") {
    return isKnownWindow(raw) ? raw : STATS_WINDOW_DEFAULT;
  }
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw.trim());
    if (Number.isFinite(n) && isKnownWindow(n)) return n;
  }
  return STATS_WINDOW_DEFAULT;
}

// Serialize back to the string localStorage stores. Symmetric with
// parseStatsWindow(serializeStatsWindow(w)).
export function serializeStatsWindow(w: StatsWindowHours): string {
  return String(w);
}

// Short human label for a window -- used in the selector buttons / aria.
export function labelForStatsWindow(w: StatsWindowHours): string {
  if (w === 168) return "7d";
  if (w === 720) return "30d";
  return "24h";
}

// --- Browser wrappers (no-throw) -----------------------------------------

// Read the persisted window. Returns the default on SSR / blocked storage /
// a corrupt value. Safe to call from a mount effect.
export function readStatsWindow(): StatsWindowHours {
  if (typeof window === "undefined") return STATS_WINDOW_DEFAULT;
  try {
    return parseStatsWindow(window.localStorage.getItem(STATS_WINDOW_STORAGE_KEY));
  } catch {
    return STATS_WINDOW_DEFAULT;
  }
}

// Persist the selected window. No-throw: swallows quota / privacy-mode
// errors so a write failure never breaks the selector.
export function writeStatsWindow(w: StatsWindowHours): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      STATS_WINDOW_STORAGE_KEY,
      serializeStatsWindow(w),
    );
  } catch {
    // Ignore -- the in-memory selection still works for this session.
  }
}
