// Two-step bulk-action confirmation for /notifications (F149). "Mark all read"
// is a one-click bulk mutation that's tedious to undo (you lose track of which
// were new). The /keys page already proved a DOM-free "click once to arm,
// click again to fire" state machine (key-confirm); this is the bulk variant:
// a single armed action, no per-row id. Reused by mark-all-read and clear-all
// so neither needs the unstyled browser confirm().

export type BulkAction = "mark_all_read" | "clear_all";

// The currently-armed bulk action, or null when nothing is awaiting a second
// click. Only one bulk action can be armed at a time.
export type BulkConfirmPending = BulkAction | null;

// True when this exact action is armed -- drives the inline "Confirm" swap.
export function bulkIsArmed(pending: BulkConfirmPending, action: BulkAction): boolean {
  return pending === action;
}

// The button label given its armed state: the verb when resting, "Confirm"
// when armed so the second click is unambiguous.
export function bulkConfirmLabel(action: BulkAction, armed: boolean): string {
  if (armed) return "Confirm";
  return action === "mark_all_read" ? "Mark all read" : "Clear all";
}

// Short consequence prompt rendered beside an armed action so the second click
// is informed, not reflexive.
export function bulkConfirmPrompt(action: BulkAction): string {
  return action === "mark_all_read"
    ? "Mark every notification read?"
    : "Clear every notification? This cannot be undone.";
}

// Resolve a click: unarmed -> arm (no fire); armed -> fire + disarm. Arming a
// different action replaces the previous one so two prompts never show at once.
export function bulkNextOnTrigger(
  pending: BulkConfirmPending,
  action: BulkAction,
): { fire: boolean; pending: BulkConfirmPending } {
  if (bulkIsArmed(pending, action)) return { fire: true, pending: null };
  return { fire: false, pending: action };
}
