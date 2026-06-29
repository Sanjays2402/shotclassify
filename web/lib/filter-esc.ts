// /shots filter toolbar Escape behaviour (F145). Pressing Esc inside any
// filter control should hand focus back to the list rather than just dropping
// it on the floor -- a small keyboard nicety so you can refine a filter and
// pop straight back to results without reaching for the mouse. Pure + DOM-free
// so the predicate is testable; HotKeys / the toolbar do the actual blur.

// Lightweight key shape; KeyboardEvent satisfies it. We only care about the
// key + whether a modifier is held (a modified Esc, if any, isn't ours).
export type EscKeyLike = {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
};

// True when this is a bare Escape we should treat as "leave the filter".
// Modified Escape (rare) is left alone. Accepts both "Escape" and the legacy
// "Esc" name browsers historically emitted.
export function isBareEscape(ev: EscKeyLike): boolean {
  if (ev.key !== "Escape" && ev.key !== "Esc") return false;
  return !ev.metaKey && !ev.ctrlKey && !ev.altKey;
}

// What an Escape should do, given whether the control still holds text. A
// non-empty text input clears first (one tap to empty, a second to leave);
// an empty / non-text control jumps straight to the list. This staged
// behaviour matches how a search box should feel under the keyboard.
export type EscAction = "clear" | "leave" | "none";

export function filterEscapeAction(
  ev: EscKeyLike,
  hasValue: boolean,
): EscAction {
  if (!isBareEscape(ev)) return "none";
  return hasValue ? "clear" : "leave";
}
