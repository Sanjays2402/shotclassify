// Build a /shots deep-link from a /stats class tile that carries the active
// time window (F60). The "All classes" grid on /stats already links each
// tile to `/shots?category=<c>`, but it dropped the window the user was
// looking at -- click a class from a 7d view and you'd land on the class
// filtered to ALL time. This threads the window through as a `since=` date so
// the destination matches what the tile was counting.
//
// Reuses buildShotsDeepLink (the F47 inverse of the F30 parser) so the link
// round-trips through the same validation the page applies on load. DOM-free
// + framework-free; takes an explicit `now` so the date math is deterministic
// in tests.

import { buildShotsDeepLink } from "./shots-deeplink";
import type { Category } from "./categories";

// Format an epoch-ms instant as a yyyy-mm-dd string in UTC. The /shots date
// filter is date-granular and interprets `since` as UTC midnight
// (`${since}T00:00:00Z`), so we format in UTC for a consistent round trip.
function ymdUTC(epochMs: number): string {
  const d = new Date(epochMs);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// The calendar date `windowHours` before `now`, as yyyy-mm-dd. This is the
// `since` the deep-link carries. Because the /shots filter is date-granular,
// the destination shows shots on or after that calendar date -- slightly
// broader than an exact rolling window, but honest about the granularity the
// list supports. A non-finite / non-positive window yields no `since` (the
// caller links to the unscoped class).
export function sinceForWindow(
  windowHours: number,
  now: number,
): string | undefined {
  if (!Number.isFinite(windowHours) || windowHours <= 0) return undefined;
  if (!Number.isFinite(now)) return undefined;
  return ymdUTC(now - windowHours * 3600 * 1000);
}

// Build the /shots deep-link for a class tile, scoped to the active window.
// `base` lets the caller pass an absolute origin for a shareable URL; it
// defaults to the relative "/shots" the grid uses today.
export function statsClassLink(
  category: Category,
  windowHours: number,
  now: number,
  base = "/shots",
): string {
  return buildShotsDeepLink(
    { category, since: sinceForWindow(windowHours, now) ?? null },
    base,
  );
}
