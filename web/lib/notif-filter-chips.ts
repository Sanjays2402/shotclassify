// Pure helpers for the notifications-inbox filter breadcrumb (F88). The
// /notifications page filters by free-text search, notification kind, and an
// unread-only toggle. This module turns that filter state into an ordered
// list of removable "chips" -- each describing one active constraint plus the
// key needed to clear just that one -- mirroring lib/filter-summary.ts for the
// shots table so the two consolidate on the same breadcrumb pattern. Keeping
// the label-building here (framework-free) makes it unit-testable and lets the
// page render a thin pill row.

// The slice of /notifications state that actually constrains the result set.
export type NotifFilterState = {
  q?: string | null;
  // The selected kind value, where "all" / null / "" means no constraint.
  kind?: string | null;
  unreadOnly?: boolean;
};

// Stable identifiers for each clearable filter. The page maps these back to
// its individual setters (setQ / setKind / setUnreadOnly).
export type NotifFilterKey = "q" | "kind" | "unread";

export type NotifFilterChip = {
  key: NotifFilterKey;
  // Full human-readable label, e.g. `Kind: Webhook failures`.
  label: string;
  // Short eyebrow shown before the value, e.g. `Kind`.
  field: string;
  // The value portion, e.g. `Webhook failures`. Empty for the boolean toggle.
  value: string;
};

// Human labels for the known notification kinds. Mirrors the page's
// KIND_OPTIONS so the chip reads "Classifications" rather than the raw
// "classify.completed" wire value. An unknown kind falls back to its raw
// value so a future kind still renders something sensible.
export const NOTIF_KIND_LABELS: Record<string, string> = {
  "classify.completed": "Classifications",
  "webhook.failed": "Webhook failures",
  system: "System",
};

// Resolve a kind value to its display label, falling back to the raw value.
export function notifKindLabel(kind: string): string {
  return NOTIF_KIND_LABELS[kind] ?? kind;
}

// Trim a long search string for display so the chip never blows out the row.
function truncate(s: string, max = 28): string {
  const t = s.trim();
  return t.length > max ? `${t.slice(0, max)}\u2026` : t;
}

// True when a kind value is actually constraining ("all" / "" / null are the
// no-op default the select starts at).
function hasKind(kind: string | null | undefined): kind is string {
  return typeof kind === "string" && kind.trim() !== "" && kind !== "all";
}

// Build the ordered chip list. Order mirrors the shots breadcrumb's reading
// order: text search first, then kind, then the unread toggle.
export function activeNotifChips(f: NotifFilterState): NotifFilterChip[] {
  const chips: NotifFilterChip[] = [];

  if (typeof f.q === "string" && f.q.trim()) {
    const value = `"${truncate(f.q)}"`;
    chips.push({ key: "q", field: "Search", value, label: `Search: ${value}` });
  }

  if (hasKind(f.kind)) {
    const value = notifKindLabel(f.kind.trim());
    chips.push({ key: "kind", field: "Kind", value, label: `Kind: ${value}` });
  }

  if (f.unreadOnly === true) {
    chips.push({
      key: "unread",
      field: "Unread",
      value: "only",
      label: "Unread only",
    });
  }

  return chips;
}

// How many filters are currently active. Cheap convenience for the renderer.
export function countActiveNotifFilters(f: NotifFilterState): number {
  return activeNotifChips(f).length;
}
