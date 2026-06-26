// A small, pure relative-time formatter (F59). The command palette's
// "Recently viewed" rows store a `viewedAt` epoch but rendered no time, so the
// MRU ordering was invisible -- two rows looked equally fresh. This turns a
// timestamp into a compact "3m ago" / "just now" / "2d ago" label rendered as
// a faint trailing hint, making the ordering legible.
//
// Pure + DOM-free (takes an explicit `now` so tests are deterministic and the
// component can pass Date.now()). Coarse buckets only -- this is a glanceable
// hint, not a precise clock, so we never show "1m 23s ago".

// Format the gap between `then` and `now` (both epoch ms) as a short relative
// phrase. Future timestamps and sub-minute gaps both collapse to "just now"
// so a slightly-skewed clock never renders "in 3s". Non-finite inputs degrade
// to "" so a malformed stored entry renders no label rather than "NaN ago".
export function relativeTime(then: number, now: number): string {
  if (!Number.isFinite(then) || !Number.isFinite(now)) return "";
  const deltaMs = now - then;
  // Future or near-now -> "just now". The 45s threshold rounds the first
  // minute up smoothly rather than flicking to "1m" the instant it passes 60s.
  if (deltaMs < 45_000) return "just now";

  const sec = deltaMs / 1000;
  const min = sec / 60;
  if (min < 60) return `${Math.round(min)}m ago`;

  const hr = min / 60;
  if (hr < 24) return `${Math.round(hr)}h ago`;

  const day = hr / 24;
  if (day < 7) return `${Math.round(day)}d ago`;

  const week = day / 7;
  if (week < 5) return `${Math.round(week)}w ago`;

  // Beyond a month we stop being precise -- "30d+ ago" reads as "a while back"
  // without implying we tracked the exact month boundary.
  return "30d+ ago";
}

// Convenience wrapper that defaults `now` to the wall clock, for component
// render sites that don't already hold a `now`.
export function relativeTimeFromNow(then: number): string {
  return relativeTime(then, Date.now());
}
