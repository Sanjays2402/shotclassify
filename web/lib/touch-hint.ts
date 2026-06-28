// Touch-affordance hint state for the /notifications inbox (F126). Each inbox
// row carries a trash button that dismisses the notification, but on a touch
// device that affordance is easy to miss -- there's no hover to reveal it and
// the icon reads as decorative. This shows a faint one-time "Tap the trash to
// dismiss" tip at the top of the list ON COARSE-POINTER (touch) viewports only,
// and remembers a dismissal so it never nags twice.
//
// Split into a DOM-free decision (shouldShowTouchHint -- a small truth table)
// plus thin, no-throw environment probes (isCoarsePointer / seen-flag storage)
// so the interesting logic is unit-testable and the component is a thin
// renderer. Mirrors lib/onboarding's fail-open storage convention.

export const TOUCH_HINT_SEEN_KEY = "shotclassify.notif-touch-hint.v1";

// Pure: should the hint render? It needs ALL of:
//  - a coarse (touch) pointer -- a mouse user already sees the icon on hover,
//  - the hint not previously dismissed,
//  - at least one row to point the tip at (no rows -> nothing to dismiss).
// Everything is passed in so this is deterministic + testable; the component
// supplies the live environment values.
export function shouldShowTouchHint(
  coarsePointer: boolean,
  seen: boolean,
  rowCount: number,
): boolean {
  if (!coarsePointer) return false;
  if (seen) return false;
  return Number.isFinite(rowCount) && rowCount > 0;
}

// Probe whether the primary pointer is coarse (a finger / stylus) rather than
// a mouse, via the `(pointer: coarse)` media query. SSR-safe (returns false
// when there's no window / matchMedia) and no-throw, so a hostile / partial
// matchMedia implementation can't break the page -- it just fails closed
// (hint hidden) which is the safe default.
export function isCoarsePointer(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  try {
    return window.matchMedia("(pointer: coarse)").matches === true;
  } catch {
    return false;
  }
}

// Has the user already dismissed the hint? Fail-OPEN as "seen" (true) when
// storage is unavailable so a private-mode / quota-blocked browser doesn't
// re-show the tip on every visit -- consistent with the rest of the file
// treating an unreadable store as "don't nag".
export function hasSeenTouchHint(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(TOUCH_HINT_SEEN_KEY) === "1";
  } catch {
    return true;
  }
}

// Remember that the hint was shown + dismissed so it never appears again.
// No-throw (storage may be unavailable); a failed write simply means the tip
// may show once more next visit, which is harmless.
export function markTouchHintSeen(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOUCH_HINT_SEEN_KEY, "1");
  } catch {
    // Storage unavailable -- no-op (fail open).
  }
}
