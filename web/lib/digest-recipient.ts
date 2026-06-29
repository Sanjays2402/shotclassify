// Pure helpers for the /digest "Send to inbox" recipient field (F153 follow-up).
// The send button POSTs whatever's typed, so a fat-fingered address (no @, a
// trailing comma, a stray space) only fails server-side after a round trip.
// This module validates the optional recipient client-side and decides the
// send-button enabled state + the inline hint, so the form catches the mistake
// before the request. DOM-free so it's unit-testable and the page stays thin.

// A blank recipient is VALID -- the server falls back to the configured
// DIGEST_TO, so "send to the default" is the empty case, not an error.
export function isBlankRecipient(raw: string | null | undefined): boolean {
  return typeof raw !== "string" || raw.trim() === "";
}

// Conservative single-address check: one local@domain.tld, no spaces, a dot in
// the domain, no double dots. Intentionally not RFC-exhaustive -- it only needs
// to catch the obvious fumble before the POST; the server is the real gate.
export function isValidRecipient(raw: string | null | undefined): boolean {
  if (typeof raw !== "string") return false;
  const e = raw.trim();
  if (e.length === 0 || e.length > 254) return false;
  if (/\s/.test(e)) return false;
  if (e.includes("..")) return false;
  return /^[^@]+@[^@]+\.[^@]+$/.test(e);
}

// The button enables when the field is blank (use default) OR a valid address
// is typed -- and the page isn't already busy. Mirrors the digest send button's
// existing disabled-on-busy behaviour, adding the malformed-address gate.
export function canSendDigest(raw: string | null | undefined, busy: boolean): boolean {
  if (busy) return false;
  return isBlankRecipient(raw) || isValidRecipient(raw);
}

// Inline hint under the input: null when blank (default delivery) or valid, a
// nudge only once something non-empty looks wrong so it doesn't scold an empty
// field on first paint.
export function recipientHint(raw: string | null | undefined): string | null {
  if (isBlankRecipient(raw)) return null;
  return isValidRecipient(raw) ? null : "Enter a single valid email, or clear to use the default.";
}
