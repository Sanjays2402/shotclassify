/**
 * Pure ranking helpers for the command palette. Kept out of the React
 * component so they're cheap to test with node --test.
 */

export function fuzzyScore(q: string, label: string, hint: string): number {
  const Q = q.toLowerCase().trim();
  if (!Q) return 1;
  const L = label.toLowerCase();
  const H = hint.toLowerCase();
  if (L.startsWith(Q)) return 100;
  if (L.includes(Q)) return 60;
  if (H.includes(Q)) return 30;
  let i = 0;
  for (const ch of L) {
    if (ch === Q[i]) i++;
    if (i >= Q.length) return 10;
  }
  return 0;
}

export type RankableNav = { id: string; label: string; hint: string };

export function rankNav<T extends RankableNav>(
  q: string,
  nav: T[],
  limit = 8,
): T[] {
  const Q = q.trim();
  if (!Q) return nav.slice(0, limit);
  return nav
    .map((n) => ({ n, s: fuzzyScore(Q, n.label, n.hint) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, limit)
    .map((x) => x.n);
}

// Map a Cmd/Ctrl + digit chord to a zero-based result index (F45). Power
// users can jump straight to the Nth flat result (nav, then recently-viewed,
// then shot hits -- the same order the palette renders and the arrow keys
// walk) without arrowing down. `1` -> index 0 ... `9` -> index 8, and `0`
// is intentionally NOT bound (there's no "10th" mnemonic and Cmd+0 is the
// browser zoom-reset). Returns null when:
//   - the key isn't a 1-9 digit,
//   - the target index is out of range for the current result count,
// so the caller can no-op (and let the browser keep its native chord) safely.
export function digitJumpIndex(
  key: string,
  itemCount: number,
): number | null {
  if (typeof key !== "string" || key.length !== 1) return null;
  if (key < "1" || key > "9") return null;
  const idx = key.charCodeAt(0) - "1".charCodeAt(0); // '1' -> 0
  if (!Number.isInteger(itemCount) || itemCount <= 0) return null;
  if (idx >= itemCount) return null;
  return idx;
}

// Resting-palette discoverability hint (F50). When the palette is open with
// NO free text / facet typed AND the recently-viewed ring is empty, the lower
// half is bare nav -- nothing explains that opening a shot will populate a
// "Recently viewed" shortcut here. This returns a one-line tip to render
// under the nav in exactly that state, and null otherwise (so the moment the
// user types, or once they've viewed a shot, the hint steps aside).
//
// `resting` is the same predicate the component already computes for whether
// to show the recents section (no residual text AND no structured facet);
// `recentCount` is the size of the recently-viewed ring.
export const PALETTE_RESTING_HINT =
  "Tip: open a shot and it shows up here for one-keystroke return.";

export function paletteRestingHint(
  resting: boolean,
  recentCount: number,
): string | null {
  if (!resting) return null;
  if (Number.isFinite(recentCount) && recentCount > 0) return null;
  return PALETTE_RESTING_HINT;
}

// Shots-list shortcut legend for the palette footer (F70). The shots page has
// single-letter shortcuts (`v` cycle view, `d` cycle grid density) that are
// only discoverable today via the `?` overlay. Surfacing them as a faint
// footer legend when the palette is open makes them reachable from anywhere,
// the same way the Cmd-digit jump legend already advertises that chord.
//
// Pure: takes the SHORTCUTS catalogue (the component passes it in so this
// module doesn't import React-adjacent code) and returns one entry per
// shots-scope shortcut, each carrying its rendered key glyph(s) + label. The
// component renders them as <kbd> chips. Anything not in the "shots" scope is
// filtered out, so adding a new shots shortcut to the catalogue lights it up
// here automatically.
export type PaletteScopeHint = {
  id: string;
  keys: string[];
  label: string;
};

type ScopedShortcut = {
  id: string;
  scope: string;
  combo: { keys: string[] };
  label: string;
};

export function shotsScopeHints(
  shortcuts: readonly ScopedShortcut[],
): PaletteScopeHint[] {
  if (!Array.isArray(shortcuts)) return [];
  return shortcuts
    .filter((s) => s && s.scope === "shots")
    .map((s) => ({
      id: s.id,
      keys: Array.isArray(s.combo?.keys) ? [...s.combo.keys] : [],
      label: s.label,
    }))
    .filter((h) => h.keys.length > 0);
}

// Condense a verbose shortcut label down to its leading verb-phrase for the
// compact footer legend (F70): the catalogue labels read like "Cycle list
// view (Table / Grid / Compact)" which is too long for a footer chip. We keep
// the text before the first parenthetical and, when it starts with "Cycle ",
// drop that lead word so "Cycle grid density (...)" -> "grid density". Falls
// back to the trimmed full label when there's nothing to strip.
export function shortLabelForHint(label: string): string {
  if (typeof label !== "string") return "";
  let s = label.split("(")[0].trim();
  if (/^cycle\s+/i.test(s)) s = s.replace(/^cycle\s+/i, "");
  return s.trim();
}

// Recently-viewed count badge for the palette's Shots nav row (F83). The
// "Recently viewed" section only appears below the nav once the ring has
// entries AND the query is empty -- so on a freshly-opened palette a user
// can't tell their last few shots are one keystroke away. Tag the Shots nav
// row with a faint "N recent" badge so the trail is discoverable before they
// scroll. Pure: returns the label for the shots route when the ring is
// non-empty, null everywhere else (other rows, empty / invalid count) so the
// component renders nothing.
export const RECENT_BADGE_ROUTE = "/shots";

export function recentCountLabel(
  href: string,
  recentCount: number,
): string | null {
  if (href !== RECENT_BADGE_ROUTE) return null;
  if (!Number.isFinite(recentCount) || recentCount <= 0) return null;
  return `${recentCount} recent`;
}
