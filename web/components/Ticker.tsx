"use client";

import useSWR from "swr";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { CATEGORIES, SHORT, type Category } from "@/lib/categories";
import { makeSampleCounts } from "@/lib/sample";

type CountMap = Partial<Record<Category, number>>;

function useCounts(): { counts: CountMap; sample: boolean } {
  // Pull recent history and bucket by category for a rolling-24h feel.
  // If the server gives nothing, fall back to seeded sample counts.
  const { data, error } = useSWR<any[]>(
    ENDPOINTS.history({ limit: 500 }),
    fetcher,
    { refreshInterval: 30_000, revalidateOnFocus: false }
  );
  if (error || !Array.isArray(data) || data.length === 0) {
    return { counts: makeSampleCounts(), sample: true };
  }
  const now = Date.now();
  const day = 24 * 60 * 60 * 1000;
  const counts: CountMap = {};
  for (const rec of data) {
    const cat = rec?.primary_category as Category | undefined;
    if (!cat) continue;
    const ts = rec?.created_at ? new Date(rec.created_at).getTime() : now;
    if (now - ts > day) continue;
    counts[cat] = (counts[cat] ?? 0) + 1;
  }
  return { counts, sample: false };
}

export default function Ticker() {
  const { counts, sample } = useCounts();
  const items = CATEGORIES.map((c) => ({ c, n: counts[c] ?? 0 }));
  const totals = items.reduce((a, b) => a + b.n, 0);

  const segment = (
    <>
      <span className="ticker-item">
        <span className="live" />
        <span>Live feed</span>
      </span>
      <span className="ticker-item">
        <span>24h</span>
        <span className="num">{totals.toLocaleString()}</span>
        <span>classifications</span>
      </span>
      {items.map(({ c, n }) => (
        <span key={c} className="ticker-item">
          <span
            className="dot"
            style={{ ["--bar" as any]: `var(--color-cat-${c.split("_")[0]})` }}
          />
          <span>{SHORT[c]}</span>
          <span className="num">{n.toLocaleString()}</span>
        </span>
      ))}
      {sample && (
        <span className="ticker-item" style={{ color: "var(--color-cue)" }}>
          ⟂ Sample data
        </span>
      )}
    </>
  );

  return (
    <div className="ticker-wrap" aria-label="Rolling 24-hour classification counts">
      <div className="ticker-track">
        {segment}
        {segment}
      </div>
    </div>
  );
}
