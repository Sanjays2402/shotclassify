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
