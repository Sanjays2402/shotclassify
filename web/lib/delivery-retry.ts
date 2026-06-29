// Pure helpers for the /webhooks delivery "retry" affordance (F147). Each row
// in the recent-deliveries table is one outbound POST attempt; failed ones can
// be re-fired via the existing action=redeliver endpoint. This module owns the
// non-DOM decisions the row button needs: is this delivery worth retrying, what
// does the button say (idle / in-flight), and the success/failure toast copy.
// Keeping it here makes the wording testable and lets the page stay a thin
// renderer that just tracks which delivery id is in flight.

// Minimal shape the helpers reason about; the page Delivery is a superset.
export type RetryableDelivery = {
  id: string;
  status: string;
  event: string;
};

// Only non-success deliveries make sense to retry -- re-firing a success is
// pointless and a pending one is still in motion. Guards a blank id so a
// half-loaded row never offers a no-op button.
export function canRetryDelivery(d: RetryableDelivery | null | undefined): boolean {
  if (!d || typeof d.id !== "string" || d.id.trim() === "") return false;
  return d.status === "failed";
}

// Button label: a bare "Retry" at rest, "Retrying..." while THIS row's POST is
// in flight (the page passes the inFlight id). Other rows stay enabled.
export function retryButtonLabel(busy: boolean): string {
  return busy ? "Retrying..." : "Retry";
}

// Accessible name folds in the event so a screen-reader user knows which row
// fires, e.g. "Retry failed delivery for classify.completed".
export function retryAriaLabel(event: string): string {
  const e = typeof event === "string" && event.trim() ? event.trim() : "event";
  return `Retry failed delivery for ${e}`;
}

// Toast copy after a redeliver attempt. Success names the event; failure
// surfaces the trimmed server message (falling back to a generic line) so a
// triager knows whether to try again.
export function retryToast(
  ok: boolean,
  event: string,
  message?: string | null,
): { kind: "success" | "error"; text: string } {
  const e = typeof event === "string" && event.trim() ? event.trim() : "delivery";
  if (ok) return { kind: "success", text: `Re-fired ${e}. Watch the table for the new attempt.` };
  const m = typeof message === "string" && message.trim() ? message.trim() : "Retry failed.";
  return { kind: "error", text: m.slice(0, 200) };
}
