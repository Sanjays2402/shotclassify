// Keyboard-open parity for ShotGrid cards (F150). In the table view a row is
// reachable and Enter opens the shot; in the card grid only the inner name
// <Link> was tabbable, so the card itself was not a single focus stop and had
// no visible ring. This pure helper decides when a key press on a focused card
// should open the shot, so the grid matches the table's keyboard behaviour.
//
// DOM-free + framework-free so it's unit-testable. The card is the focus stop;
// inner controls (select / pin / compare / preview) keep their own focus and
// must NOT be hijacked, so we only open when the event originated on the card
// itself, not a descendant button.

export type CardOpenEvent = {
  key: string;
  // True when the event target IS the card element (not a child control). The
  // caller passes `ev.target === ev.currentTarget`.
  selfTarget: boolean;
};

// Enter or Space opens the focused card, matching native button/link
// activation. Space only when the card itself is focused, never an inner
// control (whose own handler runs). Returns true => caller navigates + should
// preventDefault.
export function shouldOpenCard(ev: CardOpenEvent): boolean {
  if (!ev.selfTarget) return false;
  return ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar";
}

// The detail href for a shot id. Single source so the card link, the keyboard
// handler, and tests can't drift apart. Blank id yields "" so the caller can
// skip navigation.
export function shotDetailHref(id: string | null | undefined): string {
  const trimmed = typeof id === "string" ? id.trim() : "";
  return trimmed ? `/shots/${trimmed}` : "";
}
