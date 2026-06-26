"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { CATEGORIES, SHORT, type Category } from "@/lib/categories";
import { makeSampleCounts } from "@/lib/sample";
import { didIncrease, increasedKeys } from "@/lib/ticker-pulse";

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

// One animation frame's worth of CSS class. We add it on an increase and strip
// it after the keyframe so a later increase can re-trigger it (re-adding a
// class that's already present wouldn't restart the animation).
const PULSE_MS = 1100;

export default function Ticker() {
  const { counts, sample } = useCounts();
  const items = CATEGORIES.map((c) => ({ c, n: counts[c] ?? 0 }));
  const totals = items.reduce((a, b) => a + b.n, 0);

  // Track the previous total + per-class counts so we can glow only the
  // numbers that actually ticked UP on a revalidate (F76). Refs, not state,
  // so updating them doesn't itself trigger a render.
  const prevTotal = useRef<number | null>(null);
  const prevCounts = useRef<Record<string, number> | null>(null);
  // The transient "pulsing" set drives the CSS class; cleared after PULSE_MS.
  const [pulseTotal, setPulseTotal] = useState(false);
  const [pulseCats, setPulseCats] = useState<Set<string>>(new Set());

  useEffect(() => {
    // Sample data is static seed noise -- never pulse on it, and don't seed
    // the refs from it so the first REAL payload isn't read as a huge jump.
    if (sample) return;

    const nextCounts: Record<string, number> = {};
    for (const { c, n } of items) nextCounts[c] = n;

    if (didIncrease(prevTotal.current, totals)) {
      setPulseTotal(true);
    }
    const bumped = increasedKeys(prevCounts.current, nextCounts);
    if (bumped.length > 0) {
      setPulseCats(new Set(bumped));
    }

    prevTotal.current = totals;
    prevCounts.current = nextCounts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totals, sample]);

  // Strip the total-pulse class after the keyframe so a later tick re-fires.
  useEffect(() => {
    if (!pulseTotal) return;
    const t = setTimeout(() => setPulseTotal(false), PULSE_MS);
    return () => clearTimeout(t);
  }, [pulseTotal]);

  useEffect(() => {
    if (pulseCats.size === 0) return;
    const t = setTimeout(() => setPulseCats(new Set()), PULSE_MS);
    return () => clearTimeout(t);
  }, [pulseCats]);

  const segment = (
    <>
      <span className="ticker-item">
        <span className="live" />
        <span>Live feed</span>
      </span>
      <span className="ticker-item">
        <span>24h</span>
        <span className={`num${pulseTotal ? " sc-tick-pulse" : ""}`}>
          {totals.toLocaleString()}
        </span>
        <span>classifications</span>
      </span>
      {items.map(({ c, n }) => (
        <span key={c} className="ticker-item">
          <span
            className="dot"
            style={{ ["--bar" as any]: `var(--color-cat-${c.split("_")[0]})` }}
          />
          <span>{SHORT[c]}</span>
          <span className={`num${pulseCats.has(c) ? " sc-tick-pulse" : ""}`}>
            {n.toLocaleString()}
          </span>
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
