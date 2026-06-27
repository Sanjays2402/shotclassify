// Pure roving-tabindex math for keyboard-navigable menus / lists (F114). A
// "roving index" is the single focusable position in a composite widget (a
// menu, a toolbar): Arrow keys move it, Home/End jump to the ends, and focus
// wraps around the edges. The RowExportMenu dropdown (JSON / Markdown / CSV)
// was mouse + Enter only; this backs Up/Down/Home/End navigation between its
// items. Kept DOM-free so the index arithmetic is unit-testable; the component
// owns the actual focus() calls + the refs.

// The navigation keys we resolve. Anything else returns null so the caller
// leaves the event alone (Enter / Escape / typing are handled elsewhere).
export type RovingKey = "ArrowDown" | "ArrowUp" | "Home" | "End";

const NAV_KEYS: ReadonlySet<string> = new Set([
  "ArrowDown",
  "ArrowUp",
  "Home",
  "End",
]);

// True when a key string is one this module navigates on -- lets the caller
// cheaply decide whether to preventDefault before delegating.
export function isRovingKey(key: string): key is RovingKey {
  return NAV_KEYS.has(key);
}

// Resolve the next focused index for a roving widget. Returns null when the key
// isn't a navigation key or the list is empty (nothing to focus), so the
// caller can no-op cleanly.
//
// Semantics:
//  - ArrowDown: move forward, wrapping past the end back to the top. From an
//    unfocused state (current < 0) it lands on the FIRST item.
//  - ArrowUp:   move backward, wrapping past the top to the end. From an
//    unfocused state it lands on the LAST item (the natural "open upward").
//  - Home / End: jump straight to the first / last item.
//
// `current` is clamped into range first so a stale index (the list shrank)
// can't produce an out-of-bounds result.
export function rovingIndex(
  current: number,
  length: number,
  key: string,
): number | null {
  if (!isRovingKey(key)) return null;
  if (!Number.isFinite(length) || length <= 0) return null;
  const len = Math.trunc(length);

  // Normalise the incoming index. A negative / non-finite value means
  // "nothing focused yet"; anything past the end clamps to the last item.
  const hasFocus = Number.isFinite(current) && current >= 0;
  const cur = hasFocus ? Math.min(Math.trunc(current), len - 1) : -1;

  switch (key) {
    case "ArrowDown":
      // Unfocused -> first; otherwise step forward with wrap.
      return hasFocus ? (cur + 1) % len : 0;
    case "ArrowUp":
      // Unfocused -> last; otherwise step backward with wrap.
      return hasFocus ? (cur - 1 + len) % len : len - 1;
    case "Home":
      return 0;
    case "End":
      return len - 1;
  }
}
