// Pure keyboard math for an ARIA radio-group with roving tabindex (F128). The
// /webhooks status legend (success / failed / pending) shipped as a row of
// aria-pressed toggle buttons (F101/F116). That's serviceable, but the WAI-ARIA
// pattern for "pick exactly one of N" is a radiogroup: Arrow keys move the
// selection AND focus between options, only the active option is tabbable
// (roving tabindex), and Home/End jump to the ends. This module turns that
// pattern into framework-free, unit-testable index math layered on the F114
// roving-index helper -- the component owns the DOM focus() + the actual
// selection state.

import { rovingIndex } from "./roving-index";

// The keys a radio-group navigates on. Per the APG, both orientations are
// supported: Left/Up step to the previous option, Right/Down to the next,
// Home/End to the first/last. We normalise every one onto the roving-index
// vocabulary (ArrowUp/ArrowDown/Home/End) so the wrap math lives in one place.
const RADIO_NAV_KEYS: ReadonlySet<string> = new Set([
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "ArrowDown",
  "Home",
  "End",
]);

// True when a key is one this module navigates on, so the caller can cheaply
// decide whether to preventDefault before delegating.
export function isRadioNavKey(key: string): boolean {
  return RADIO_NAV_KEYS.has(key);
}

// Resolve the next selected index for a radiogroup keydown. Returns null when
// the key isn't a navigation key or there are no options, so the caller no-ops
// cleanly (Tab / Space / Enter are handled elsewhere). Left+Up map to the
// previous option, Right+Down to the next (both wrap at the edges), Home/End
// jump to the ends -- matching the WAI-ARIA radio-group keyboard contract.
//
// `current` is the index of the currently-selected option, or -1 when nothing
// is selected yet; a forward key from -1 lands on the first option and a
// backward key on the last (inherited from rovingIndex's unfocused semantics).
export function radioNavIndex(
  current: number,
  length: number,
  key: string,
): number | null {
  if (!isRadioNavKey(key)) return null;
  // Collapse the four arrows onto the two roving directions.
  let rovingKey: string;
  switch (key) {
    case "ArrowLeft":
    case "ArrowUp":
      rovingKey = "ArrowUp";
      break;
    case "ArrowRight":
    case "ArrowDown":
      rovingKey = "ArrowDown";
      break;
    default:
      // Home / End pass straight through.
      rovingKey = key;
  }
  return rovingIndex(current, length, rovingKey);
}

// Which option index should carry tabIndex={0} (be in the tab order) -- the
// rest get tabIndex={-1}, so Tab enters the group at the active option and the
// next Tab leaves it entirely (roving tabindex). When nothing is selected yet
// (-1), the FIRST option is tabbable so the group is keyboard-reachable; a
// selected index is clamped into range so a stale index can't orphan focus.
//
// Returns -1 only for a genuinely empty group (nothing to focus).
export function radioTabbableIndex(
  selectedIndex: number,
  length: number,
): number {
  if (!Number.isFinite(length) || length <= 0) return -1;
  const len = Math.trunc(length);
  if (!Number.isFinite(selectedIndex) || selectedIndex < 0) return 0;
  return Math.min(Math.trunc(selectedIndex), len - 1);
}
