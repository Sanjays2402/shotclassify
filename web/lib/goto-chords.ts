// Linear-style "go to" chord navigation (F57). Pressing `g` then a letter
// jumps straight to a section -- `g s` -> Stats, `g h` -> sHots, `g u` ->
// Upload, `g l` -> Live, `g c` -> Calibration. The two-stroke sequence
// tracker in lib/shortcuts.ts already owns the timing / buffering / reset
// logic (the existing `g t` scroll-to-top chord proves it out); this module
// is the pure source of truth mapping a COMPLETED chord to its route, plus
// the catalogue the shortcuts-help overlay renders. DOM-free + framework-free
// so the mapping is unit-testable without a router or window.
//
// Why chords when bare `s` / `u` / `c` already navigate? `g s` fills a real
// gap -- there is no bare key for /stats -- and a consistent `g <x>` namespace
// is more discoverable than a scatter of single letters. The bare letters
// stay as a legacy fast-path; the chords never collide with them because the
// HotKeys handler resolves a completed chord BEFORE it falls through to the
// single-letter switch.

export type GotoChord = {
  // The space-joined key sequence the tracker emits when the chord completes,
  // e.g. "g s". Lowercase, single space between strokes.
  seq: string;
  // The destination route pushed onto the router.
  route: string;
  // Label for the cheat-sheet ("Go to Stats").
  label: string;
  // The two glyphs rendered in the help overlay, e.g. ["G", "S"].
  keys: [string, string];
};

// The catalogue. Order is the order they render in the help overlay's
// "Jump to a section" group. `g t` is intentionally NOT here -- it's the
// scroll-to-top action HotKeys handles specially, not a section jump.
//
// Second-letter assignment avoids collisions with `g t` (scroll-to-top) and
// each other. We use a memorable letter where the first letter is free and
// fall back to a distinctive one when it's taken: Demo->D, Webhooks->W,
// API keys->K (Keys), Inbox->I. None reuse L/H/S/U/C/T.
export const GOTO_CHORDS: readonly GotoChord[] = [
  { seq: "g l", route: "/", label: "Go to Live", keys: ["G", "L"] },
  { seq: "g h", route: "/shots", label: "Go to Shots", keys: ["G", "H"] },
  { seq: "g s", route: "/stats", label: "Go to Stats", keys: ["G", "S"] },
  { seq: "g u", route: "/upload", label: "Go to Upload", keys: ["G", "U"] },
  {
    seq: "g c",
    route: "/calibration",
    label: "Go to Calibration",
    keys: ["G", "C"],
  },
  { seq: "g d", route: "/demo", label: "Go to Demo", keys: ["G", "D"] },
  { seq: "g w", route: "/webhooks", label: "Go to Webhooks", keys: ["G", "W"] },
  { seq: "g k", route: "/keys", label: "Go to API keys", keys: ["G", "K"] },
  { seq: "g i", route: "/notifications", label: "Go to Inbox", keys: ["G", "I"] },
] as const;

// Pre-built lookup so resolution is O(1) and the normalisation rules live in
// exactly one place.
const BY_SEQ: ReadonlyMap<string, string> = new Map(
  GOTO_CHORDS.map((c) => [c.seq, c.route]),
);

// Reverse index: route -> chord. Lets a consumer that already knows a
// destination (e.g. the command palette's nav rows) surface the chord that
// reaches it, keeping GOTO_CHORDS the single source of truth. Routes are
// unique (a GOTO_CHORDS invariant the tests enforce) so this is unambiguous.
const BY_ROUTE: ReadonlyMap<string, GotoChord> = new Map(
  GOTO_CHORDS.map((c) => [c.route, c]),
);

// Find the section chord that navigates to `route`, or null when no chord
// targets it. Pure + defensive so a non-string / unknown route degrades to
// null rather than throwing into a render path. Backs the palette's chord
// hint (F68): each nav row whose href matches a chord renders the `g <x>`
// glyphs so the shortcut is discoverable without opening the cheat sheet.
export function chordForRoute(
  route: string | null | undefined,
): GotoChord | null {
  if (typeof route !== "string") return null;
  return BY_ROUTE.get(route) ?? null;
}

// The two glyphs (e.g. ["G", "S"]) for the chord that reaches `route`, or
// null when none does. Thin convenience over chordForRoute for a renderer
// that only needs the keys to draw <kbd> badges.
export function chordKeysForRoute(
  route: string | null | undefined,
): readonly [string, string] | null {
  const c = chordForRoute(route);
  return c ? c.keys : null;
}

// Map a completed chord sequence to its destination route. Returns null for
// any sequence we don't own -- notably "g t" (scroll-to-top, handled by the
// caller) and any unknown chord -- so HotKeys can fall through to its other
// handlers. Whitespace + case are normalised so a tracker that ever emits
// "G  S" still resolves, and a non-string input degrades to null rather than
// throwing into the keydown handler.
export function routeForChord(seq: string | null | undefined): string | null {
  if (typeof seq !== "string") return null;
  const trimmed = seq.trim();
  if (!trimmed) return null;
  const norm = trimmed.toLowerCase().split(/\s+/).join(" ");
  return BY_SEQ.get(norm) ?? null;
}

// True when a sequence is one of our nav chords. Thin wrapper over
// routeForChord for call sites that only need a boolean.
export function isGotoChord(seq: string | null | undefined): boolean {
  return routeForChord(seq) !== null;
}
