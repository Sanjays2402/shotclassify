// Pure helpers for the /webhooks "Recent deliveries" filter + breadcrumb
// (F92). The deliveries table lists every outbound POST attempt with a status
// (success / failed / pending) and an event name. This module owns (a) the
// actual filtering of the delivery list and (b) turning the active filter
// into an ordered list of removable "chips" -- each describing one constraint
// plus the key to clear just that one -- mirroring lib/notif-filter-chips.ts
// (F88) and lib/filter-summary.ts (the shots breadcrumb) so all three list
// surfaces consolidate on one pattern. Framework-free so it's unit-testable
// and the page + breadcrumb component stay thin renderers.

// The minimal shape of a delivery row this module needs to reason about. The
// page's Delivery type is a superset; we only read status + event so the
// filter stays decoupled from the wire schema.
export type DeliveryLike = {
  status: string;
  event: string;
};

// The slice of /webhooks deliveries-view state that constrains the table.
// "all" / null / "" on either field means "no constraint".
export type WebhookDeliveryFilterState = {
  status?: string | null;
  event?: string | null;
};

// Stable identifiers for each clearable filter. The page maps these back to
// its setters (setStatusFilter / setEventFilter).
export type WebhookDeliveryFilterKey = "status" | "event";

export type WebhookDeliveryChip = {
  key: WebhookDeliveryFilterKey;
  // Full human-readable label, e.g. `Status: Failed`.
  label: string;
  // Short eyebrow shown before the value, e.g. `Status`.
  field: string;
  // The value portion, e.g. `Failed`.
  value: string;
};

// The three known delivery statuses, in the order a triaging user cares
// about (failures first). Drives the status <select> options.
export const DELIVERY_STATUSES = ["success", "failed", "pending"] as const;
export type DeliveryStatus = (typeof DELIVERY_STATUSES)[number];

// Title-cased labels for the known statuses. An unknown status falls back to
// its raw value so a future status still renders something sensible.
export const DELIVERY_STATUS_LABELS: Record<string, string> = {
  success: "Success",
  failed: "Failed",
  pending: "Pending",
};

// Resolve a status value to its display label, falling back to the raw value.
export function deliveryStatusLabel(status: string): string {
  return DELIVERY_STATUS_LABELS[status] ?? status;
}

// True when a select value is actually constraining ("all" / "" / null are
// the no-op default both selects start at).
function isConstraining(v: string | null | undefined): v is string {
  return typeof v === "string" && v.trim() !== "" && v !== "all";
}

// The distinct event names present in the delivery list, sorted, so the page
// can build the event <select> from what actually arrived rather than a
// hard-coded list (the subscribed event set may grow). Blank / non-string
// events are skipped.
export function distinctDeliveryEvents(
  deliveries: readonly DeliveryLike[],
): string[] {
  if (!Array.isArray(deliveries)) return [];
  const seen = new Set<string>();
  for (const d of deliveries) {
    const ev = typeof d?.event === "string" ? d.event.trim() : "";
    if (ev) seen.add(ev);
  }
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

// Apply the active filter to a delivery list. Pure: returns a new array with
// only the rows matching every active constraint. An inert filter returns the
// list unchanged (same elements). Status / event comparisons are exact.
export function filterDeliveries<T extends DeliveryLike>(
  deliveries: readonly T[],
  f: WebhookDeliveryFilterState,
): T[] {
  if (!Array.isArray(deliveries)) return [];
  const wantStatus = isConstraining(f.status) ? f.status.trim() : null;
  const wantEvent = isConstraining(f.event) ? f.event.trim() : null;
  if (!wantStatus && !wantEvent) return [...deliveries];
  return deliveries.filter((d) => {
    if (wantStatus && d.status !== wantStatus) return false;
    if (wantEvent && d.event !== wantEvent) return false;
    return true;
  });
}

// Build the ordered chip list. Status first (the coarsest, most-triaged cut),
// then event -- the way a user would describe "show me failed classify
// deliveries".
export function activeDeliveryChips(
  f: WebhookDeliveryFilterState,
): WebhookDeliveryChip[] {
  const chips: WebhookDeliveryChip[] = [];

  if (isConstraining(f.status)) {
    const value = deliveryStatusLabel(f.status.trim());
    chips.push({ key: "status", field: "Status", value, label: `Status: ${value}` });
  }

  if (isConstraining(f.event)) {
    const value = f.event.trim();
    chips.push({ key: "event", field: "Event", value, label: `Event: ${value}` });
  }

  return chips;
}

// How many filters are currently active. Cheap convenience for the renderer.
export function countActiveDeliveryFilters(
  f: WebhookDeliveryFilterState,
): number {
  return activeDeliveryChips(f).length;
}
