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
