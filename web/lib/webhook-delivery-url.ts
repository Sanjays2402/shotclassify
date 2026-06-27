// URL persistence for the /webhooks "Recent deliveries" filter (F103). The
// status + event filter (F92) lived only in component state, so a reload --
// or a shared link -- dropped the triage view you'd set up. This module
// mirrors the shots deep-link pattern (lib/shots-deeplink.ts) at small scale:
// a validated parse from a {get(name)} param source and a symmetric build
// back to a query string, so the webhooks page can read the filter once on
// mount and rewrite the URL whenever it changes. DOM-free + framework-free so
// it's unit-testable; the page wires the browser bits (location + replaceState).

import {
  DELIVERY_STATUSES,
  type WebhookDeliveryFilterState,
} from "./webhook-delivery-chips";

// The query-param names. Kept short + stable; documented so a shared link is
// legible (`?dstatus=failed&devent=classify.completed`). Prefixed with `d`
// (delivery) so they never collide with other webhooks-page params later.
export const DELIVERY_STATUS_PARAM = "dstatus";
export const DELIVERY_EVENT_PARAM = "devent";

// Anything with a string-or-null `get(name)` accessor. URLSearchParams
// satisfies this, and tests can pass a hand-rolled stub.
export type ParamSource = {
  get(name: string): string | null;
};

const KNOWN_STATUSES: ReadonlySet<string> = new Set(DELIVERY_STATUSES);

// The page treats "all" / "" as "no constraint"; the selects start there.
// We only emit / accept a value when it's an actual constraint, so a bare URL
// stays bare and a round trip through build(parse(x)) is stable.
function statusConstraint(v: string | null | undefined): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim().toLowerCase();
  return t && t !== "all" && KNOWN_STATUSES.has(t) ? t : null;
}

// The event filter accepts any non-blank token -- the subscribed event set is
// open-ended (a newly-subscribed event should round-trip), so unlike status we
// don't validate against a fixed list. We cap the length so a hand-mangled URL
// can't stuff an essay into the filter, and reject "all" (the no-op default).
const EVENT_MAX = 128;
function eventConstraint(v: string | null | undefined): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  if (!t || t.toLowerCase() === "all") return null;
  return t.slice(0, EVENT_MAX);
}

// Parse the deliveries filter out of a param source. Returns a state slice
// using the page's "all" sentinel for an absent / inert constraint, so the
// page can apply it directly to its statusFilter / eventFilter state. A
// malformed or empty URL yields the all/all default rather than throwing.
export function parseDeliveryFilterFromParams(
  src: ParamSource | null | undefined,
): WebhookDeliveryFilterState {
  if (!src || typeof src.get !== "function") {
    return { status: "all", event: "all" };
  }
  const status = statusConstraint(src.get(DELIVERY_STATUS_PARAM));
  const event = eventConstraint(src.get(DELIVERY_EVENT_PARAM));
  return {
    status: status ?? "all",
    event: event ?? "all",
  };
}

// True when the parsed/derived filter actually constrains the list -- lets the
// page skip a needless URL rewrite when nothing is active.
export function hasDeliveryFilter(f: WebhookDeliveryFilterState): boolean {
  return statusConstraint(f.status) !== null || eventConstraint(f.event) !== null;
}

// Build the query string (WITHOUT a leading "?") for the current filter. Only
// active constraints are emitted, in a stable order (status then event), so a
// shared link is tight and round-trips through the parser. Returns "" when no
// filter is active so the caller can drop the query entirely.
export function buildDeliveryFilterQuery(
  f: WebhookDeliveryFilterState,
): string {
  const usp = new URLSearchParams();
  const status = statusConstraint(f.status);
  if (status) usp.set(DELIVERY_STATUS_PARAM, status);
  const event = eventConstraint(f.event);
  if (event) usp.set(DELIVERY_EVENT_PARAM, event);
  return usp.toString();
}

// Compose the next same-document URL (path + optional ?query) for the current
// filter, preserving the page's pathname. The page hands `history.replaceState`
// this so a reload keeps the triage view but the back button isn't polluted
// with every filter tweak. A bare filter returns just the pathname so the URL
// cleans up to `/webhooks` when you clear everything.
export function deliveryFilterUrl(
  pathname: string,
  f: WebhookDeliveryFilterState,
): string {
  const base = typeof pathname === "string" && pathname ? pathname : "/webhooks";
  const qs = buildDeliveryFilterQuery(f);
  return qs ? `${base}?${qs}` : base;
}

// --- Shareable link (F113) -----------------------------------------------
// The "Copy link" button on the deliveries view serialises the CURRENT filter
// into an absolute URL a teammate can open to land on the same triage view.
// Mirrors lib/shots-deeplink's buildShotsDeepLink: pass an absolute origin as
// `base` (e.g. `${location.origin}/webhooks`) to get a shareable URL; the bare
// base comes back when no filter is active (the caller disables the button in
// that case, so the link is never just the plain page).
export function buildDeliveryDeepLink(
  f: WebhookDeliveryFilterState,
  base = "/webhooks",
): string {
  const qs = buildDeliveryFilterQuery(f);
  return qs ? `${base}?${qs}` : base;
}

// Title-cased status word for the toast. Reuses the param validator so the
// toast and the URL can never disagree on what counts as a status.
function statusPhrase(f: WebhookDeliveryFilterState): string | null {
  const s = statusConstraint(f.status);
  if (!s) return null;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// The toast line for a successful copy. Names the active constraints so the
// user trusts the link carries their filter ("Copied a link to Failed
// classify.completed deliveries."), else a generic confirmation. Pure; reuses
// the same constraint rules as the query builder so prose + URL stay in sync.
export function deliveryLinkToastMessage(
  f: WebhookDeliveryFilterState,
): string {
  const parts: string[] = [];
  const status = statusPhrase(f);
  if (status) parts.push(status);
  const event = eventConstraint(f.event);
  if (event) parts.push(event);
  if (parts.length === 0) {
    return "Copied a link to this deliveries view.";
  }
  return `Copied a link to ${parts.join(" ")} deliveries.`;
}

// --- Browser wrappers (no-throw) -----------------------------------------

// Read the persisted filter from the live URL. Returns the all/all default on
// SSR / a parser-less environment. Safe to call from a mount effect.
export function readDeliveryFilterFromUrl(): WebhookDeliveryFilterState {
  if (typeof window === "undefined") {
    return { status: "all", event: "all" };
  }
  try {
    const usp = new URLSearchParams(window.location.search);
    return parseDeliveryFilterFromParams(usp);
  } catch {
    return { status: "all", event: "all" };
  }
}

// Rewrite the URL query in place (no navigation, no scroll, no history entry)
// to reflect the active filter. No-throw: a blocked History API (sandboxed
// iframe, old browser) silently leaves the in-memory filter working.
export function writeDeliveryFilterToUrl(
  f: WebhookDeliveryFilterState,
): void {
  if (typeof window === "undefined") return;
  try {
    const path = window.location.pathname || "/webhooks";
    const next = deliveryFilterUrl(path, f);
    window.history.replaceState(window.history.state, "", next);
  } catch {
    // Ignore -- the in-memory filter still works for this session.
  }
}
