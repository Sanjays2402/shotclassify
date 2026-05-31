// Pure helpers used by the dynamic Open Graph image route at
// app/r/[id]/opengraph-image.tsx. Extracted so the logic is unit-testable
// without instantiating ImageResponse (which requires the edge/node runtime).

export function ogTierColor(score: number): string {
  if (score >= 0.8) return "#34d399";
  if (score >= 0.55) return "#fbbf24";
  return "#fb7185";
}

export function ogFmtFilename(name: string): string {
  if (name.length <= 48) return name;
  return name.slice(0, 22) + "..." + name.slice(-22);
}

export function ogTopThree(
  list: { category: string; score: number }[] | undefined,
): { category: string; score: number }[] {
  if (!list || list.length === 0) return [];
  return [...list].sort((a, b) => b.score - a.score).slice(0, 3);
}

export function ogBarWidthPct(score: number): number {
  if (!Number.isFinite(score)) return 6;
  if (score <= 0) return 6;
  if (score >= 1) return 100;
  return Math.max(6, Math.round(score * 100));
}
