// In-app destructive-action confirmation for the /keys page (F136). The
// rotate + revoke buttons used the browser confirm() dialog -- unstyled,
// jarring, untestable, and impossible to theme. This pure, DOM-free helper
// models the two-step "click once to arm, click Confirm to fire" flow as a
// tiny state machine keyed by (action, id), so a row can show an inline
// "Are you sure? Confirm / Cancel" affordance instead. The page holds one
// pending value and feeds clicks through here.

export type KeyConfirmAction = "rotate" | "revoke";

// One armed confirmation: which destructive action, on which key. null = no
// row is awaiting confirmation.
export type KeyConfirmPending = { action: KeyConfirmAction; id: string } | null;

// Arm a fresh confirmation. Arming a new (action,id) always replaces any
// previous one -- only ever one row is awaiting confirmation at a time.
export function armConfirm(
  action: KeyConfirmAction,
  id: string,
): KeyConfirmPending {
  return { action, id };
}

// True when this exact (action,id) is the armed one -- drives the inline
// "Are you sure?" swap on that one button.
export function isArmed(
  pending: KeyConfirmPending,
  action: KeyConfirmAction,
  id: string,
): boolean {
  return !!pending && pending.action === action && pending.id === id;
}

// Whether ANY confirmation is armed for this id (either action), so the row
// can dim/disable its other controls while one is pending. Pure read.
export function rowIsArmed(pending: KeyConfirmPending, id: string): boolean {
  return !!pending && pending.id === id;
}

// The destructive button's label given its current armed state. Unarmed
// shows the verb; armed shows "Confirm" so the second click is unambiguous.
export function confirmLabel(action: KeyConfirmAction, armed: boolean): string {
  if (armed) return "Confirm";
  return action === "rotate" ? "Rotate" : "Revoke";
}

// The short prompt rendered beside the armed buttons. Names the consequence so
// the second click is informed, not reflexive.
export function confirmPrompt(action: KeyConfirmAction): string {
  return action === "rotate"
    ? "Rotate this key? The current secret stops working immediately."
    : "Revoke this key? Calls using it start failing immediately.";
}

// Resolve a click on the destructive button: if it's not yet armed, arm it
// (no fire); if it IS armed, return fire=true so the caller runs the action.
// Keeps the two-step rule in one place rather than scattered across handlers.
export function nextOnTrigger(
  pending: KeyConfirmPending,
  action: KeyConfirmAction,
  id: string,
): { fire: boolean; pending: KeyConfirmPending } {
  if (isArmed(pending, action, id)) {
    return { fire: true, pending: null };
  }
  return { fire: false, pending: armConfirm(action, id) };
}
