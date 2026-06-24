// Source of truth for the keyboard shortcuts help overlay (and command-palette
// hints). Pure data + a pure key matcher so we can unit-test the matcher
// without importing React / window. The actual binding lives in
// components/HotKeys.tsx and the modal trigger in components/ShortcutsHelp.tsx.

export type ShortcutKey = {
  // What to render visually. e.g. ["U"], ["⌘", "K"], ["?"].
  keys: string[];
  // The platform-agnostic match string we feed `matchesShortcut`. e.g.
  //   "u"            -> single bare key
  //   "mod+k"        -> Cmd on macOS, Ctrl elsewhere
  //   "shift+/"      -> "?"
  match: string;
};

export type Shortcut = {
  id: string;
  // Where this shortcut applies. "global" = any page outside text inputs.
  scope: "global" | "shots" | "detail";
  combo: ShortcutKey;
  label: string;
  // Optional second hint that renders in the right-hand column of the modal.
  hint?: string;
};

export const SHORTCUTS: readonly Shortcut[] = [
  {
    id: "open-palette",
    scope: "global",
    combo: { keys: ["⌘", "K"], match: "mod+k" },
    label: "Open command palette",
    hint: "or press / outside an input",
  },
  {
    id: "open-help",
    scope: "global",
    combo: { keys: ["?"], match: "shift+/" },
    label: "Show this help",
  },
  {
    id: "ingest",
    scope: "global",
    combo: { keys: ["U"], match: "u" },
    label: "Open upload (ingest a frame)",
  },
  {
    id: "shots",
    scope: "global",
    combo: { keys: ["S"], match: "s" },
    label: "Browse all shots",
  },
  {
    id: "calibration",
    scope: "global",
    combo: { keys: ["C"], match: "c" },
    label: "Open calibration replay booth",
  },
  {
    id: "escape",
    scope: "global",
    combo: { keys: ["Esc"], match: "escape" },
    label: "Close any open modal",
  },
  {
    id: "to-top",
    scope: "global",
    combo: { keys: ["G", "T"], match: "g t" },
    label: "Scroll to top of page",
    hint: "Press G, then T",
  },
] as const;

// A minimal, framework-free representation of a key event so the matcher is
// testable without a DOM. KeyboardEvent satisfies this shape.
export type KeyLike = {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
};

// Detect macOS for "mod+X" rendering and matching. Falls back to false when
// the navigator is unknown (server-side / tests).
export function isMac(platform?: string): boolean {
  if (typeof platform !== "string") return false;
  return /Mac|iPhone|iPad|iPod/i.test(platform);
}

// Render the keys for a shortcut, swapping ⌘ <-> Ctrl based on platform so
// users see the right glyph. Pure -- accepts platform string.
export function renderKeys(combo: ShortcutKey, platform: string): string[] {
  const mac = isMac(platform);
  return combo.keys.map((k) => {
    if (k === "⌘" && !mac) return "Ctrl";
    if (k === "Ctrl" && mac) return "⌘";
    return k;
  });
}

// US-keyboard shifted-glyph alternates for punctuation. Browsers deliver
// shift+/ as ev.key === "?", so when a match string says "shift+/" we need
// to accept either glyph. Keep this small and US-only; non-US keyboards
// will simply fall through to letter / digit comparisons.
const SHIFTED_GLYPH: Record<string, string> = {
  "1": "!",
  "2": "@",
  "3": "#",
  "4": "$",
  "5": "%",
  "6": "^",
  "7": "&",
  "8": "*",
  "9": "(",
  "0": ")",
  "-": "_",
  "=": "+",
  "[": "{",
  "]": "}",
  "\\": "|",
  ";": ":",
  "'": '"',
  ",": "<",
  ".": ">",
  "/": "?",
  "`": "~",
};

// Returns true when the KeyboardEvent satisfies the match-string semantics.
// Modifier-prefixed combos require the modifier; bare combos require NO
// non-shift modifier so "u" doesn't match Cmd-U or Ctrl-U.
// Multi-stroke combos ("g t") are NOT handled here -- they're stateful and
// live in the HotKeys component.
export function matchesShortcut(
  match: string,
  ev: KeyLike,
  platform?: string,
): boolean {
  // Multi-key sequences are deferred to a sequence tracker.
  if (match.includes(" ")) return false;

  const parts = match.toLowerCase().split("+");
  const want = parts[parts.length - 1];
  const mods = new Set(parts.slice(0, -1));

  const isModCombo = mods.has("mod") || mods.has("cmd") || mods.has("ctrl");
  const mac = isMac(platform);
  const wantMeta =
    mods.has("cmd") || (mods.has("mod") && mac);
  const wantCtrl =
    mods.has("ctrl") || (mods.has("mod") && !mac);
  const wantAlt = mods.has("alt") || mods.has("option");
  const wantShift = mods.has("shift");

  if (!!ev.metaKey !== wantMeta) return false;
  if (!!ev.ctrlKey !== wantCtrl) return false;
  if (!!ev.altKey !== wantAlt) return false;

  // Bare combos: forbid every modifier that we didn't request, INCLUDING
  // shift -- except when the "key" itself is one that requires shift to type
  // (e.g. "?"). We treat keys whose `ev.key` already carries the shifted
  // glyph as implicitly-shifted.
  const evKey = ev.key.toLowerCase();
  if (!isModCombo) {
    if (!wantShift && !!ev.shiftKey && want.length === 1) {
      // Lone shift on a single-char bare combo is rejected unless the typed
      // character itself implies shift (then ev.key === want and we accept).
      if (evKey !== want) return false;
    }
  } else {
    if (!!ev.shiftKey !== wantShift) return false;
  }

  // Match key. "escape" and "enter" are matched by name; punctuation keys
  // like "/" are matched against ev.key directly. Letters: case-insensitive.
  if (want === "escape") return ev.key === "Escape" || ev.key === "Esc";
  if (want === "enter") return ev.key === "Enter";

  // Direct match (case-insensitive). The browser delivers letters in the
  // case implied by shift, so lowercasing both sides handles A vs a.
  if (evKey === want) return true;

  // Shift+punctuation alias: when caller asked for shift+/ and the user
  // typed "?", accept it. Symmetric: shift+? typed as / shouldn't ever
  // happen but we accept that fallthrough so non-US layouts that put /
  // behind shift still hit the help dialog.
  if (wantShift) {
    const shifted = SHIFTED_GLYPH[want];
    if (shifted && ev.key === shifted) return true;
  }
  return false;
}

// A lightweight FSM for multi-stroke sequences like "g t". The caller feeds
// every keydown event in order and the tracker tells them which (if any)
// sequence-shortcut fired. The window argument is the inter-stroke timeout
// in milliseconds (default 1200ms, matching Linear's behaviour).
export function createSequenceTracker(
  shortcuts: readonly Shortcut[],
  windowMs = 1200,
): {
  feed: (ev: KeyLike, nowMs: number) => string | null;
  reset: () => void;
} {
  const sequences = shortcuts
    .map((s) => s.combo.match)
    .filter((m) => m.includes(" "))
    .map((m) => m.toLowerCase().split(/\s+/));

  let buf: string[] = [];
  let lastTs = 0;

  function reset() {
    buf = [];
    lastTs = 0;
  }

  function feed(ev: KeyLike, nowMs: number): string | null {
    // Modifier keys / sequence-aware shortcuts only accept bare letters /
    // digits. Drop on any active modifier so Cmd-G doesn't seed "g".
    if (ev.metaKey || ev.ctrlKey || ev.altKey) {
      reset();
      return null;
    }
    if (typeof ev.key !== "string" || ev.key.length !== 1) {
      // A non-printable key (Escape, Arrow*, etc) breaks any in-flight
      // sequence so it doesn't bleed across navigations.
      reset();
      return null;
    }
    const k = ev.key.toLowerCase();
    if (nowMs - lastTs > windowMs) buf = [];
    buf.push(k);
    lastTs = nowMs;

    // Did we hit a complete sequence?
    for (const seq of sequences) {
      if (
        seq.length === buf.length &&
        seq.every((s, i) => s === buf[i])
      ) {
        reset();
        return seq.join(" ");
      }
    }
    // Trim buf to longest possible prefix of any sequence -- if the current
    // tail isn't a prefix of anything, keep only the last char so a fresh
    // sequence can start without forcing the user to wait out the timeout.
    const stillPrefix = sequences.some(
      (seq) =>
        seq.length > buf.length &&
        seq.slice(0, buf.length).every((s, i) => s === buf[i]),
    );
    if (!stillPrefix) buf = [k];
    return null;
  }

  return { feed, reset };
}
