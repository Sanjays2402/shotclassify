// Cross-page date-format helper (F154). Date rendering had drifted across the
// app: settings pages call `new Date(iso).toLocaleString()`, audit rows splice
// their own variants, the shots header builds yet another. Same ISO string,
// three slightly different visible shapes. This is the single, DOM-free source
// of truth so a date reads identically on /settings, /audit, /webhooks and
// every list header -- and a malformed timestamp degrades gracefully instead
// of printing "Invalid Date".
//
// Pure: each formatter takes an explicit locale-agnostic Intl call but is fed
// only a parsed timestamp, so tests assert the parse/guard contract (the human
// string is the browser's job). The value is consistency + the bad-input
// guard, not bespoke spelling.

// Parse an ISO-ish string OR epoch ms into a finite epoch, or null when it
// isn't a real instant. Empty / non-finite / "Invalid Date" all collapse to
// null so callers render an em dash rather than garbage.
export function parseInstant(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const t = value.trim();
  if (!t) return null;
  const ms = Date.parse(t);
  return Number.isFinite(ms) ? ms : null;
}

// The placeholder shown when there is no valid instant -- one em dash, used
// everywhere so an empty cell looks intentional and aligned.
export const NO_DATE = "\u2014";

// "Jun 28, 2026" -- a stable short date for list rows and table cells. Drops
// the clock so dense lists stay scannable.
export function shortDate(value: string | number | null | undefined): string {
  const ms = parseInstant(value);
  if (ms === null) return NO_DATE;
  return new Date(ms).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// "Jun 28, 2026, 2:05 PM" -- short date plus minute-precision clock, for
// detail panels / audit rows where the exact time matters.
export function shortDateTime(value: string | number | null | undefined): string {
  const ms = parseInstant(value);
  if (ms === null) return NO_DATE;
  return new Date(ms).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// "2026-06-28" -- a sortable yyyy-mm-dd day key, locale-independent (UTC) so
// chart buckets / since-until filters / dedupe keys never wobble by timezone.
// Returns "" for a bad input so a key-builder no-ops cleanly.
export function isoDay(value: string | number | null | undefined): string {
  const ms = parseInstant(value);
  if (ms === null) return "";
  return new Date(ms).toISOString().slice(0, 10);
}

// True when a string/number names a real instant. Lets a caller branch on
// "show the date" vs "show a placeholder" without re-parsing.
export function isValidInstant(value: string | number | null | undefined): boolean {
  return parseInstant(value) !== null;
}
