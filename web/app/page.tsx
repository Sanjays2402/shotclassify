"use client";

import Link from "next/link";
import useSWR from "swr";
import Feed from "@/components/Feed";
import LiveSampleStrip from "@/components/LiveSampleStrip";
import { Chip } from "@/components/Chip";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { CATEGORIES, SHORT } from "@/lib/categories";
import { makeSampleCounts } from "@/lib/sample";

export default function HomePage() {
  const { data: stats } = useSWR<{ count: number }>(ENDPOINTS.stats, fetcher, {
    refreshInterval: 30_000,
  });
  const total = stats?.count ?? 0;

  // Lifetime per-category mix for the side panel.
  const { data: recent, error } = useSWR<any[]>(
    ENDPOINTS.history({ limit: 500 }),
    fetcher,
    { refreshInterval: 30_000 }
  );
  const sampleMix = !Array.isArray(recent) || recent.length === 0 || !!error;
  const mix = (() => {
    if (sampleMix) return makeSampleCounts();
    const m: Record<string, number> = {};
    for (const r of recent!) {
      const c = r?.primary_category;
      if (!c) continue;
      m[c] = (m[c] ?? 0) + 1;
    }
    return m;
  })();
  const mixTotal = Object.values(mix).reduce((a, b) => a + (b as number), 0) || 1;

  return (
    <div className="flex flex-col gap-8">
      {/* Hero */}
      <section className="felt p-6 md:p-8">
        <div className="grid md:grid-cols-[1.2fr_1fr] gap-6 items-end relative z-10">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <span className="live" style={{ color: "var(--color-chalk)" }}>
                On the wire
              </span>
              <span className="eyebrow" style={{ color: "var(--color-chalk)" }}>
                {sampleMix ? "Seeded preview" : "Live"}
              </span>
            </div>
            <h1 className="h-display text-[44px] md:text-[68px]">
              SCREENSHOTS<br />
              <span style={{ color: "var(--color-cue)" }}>CALLED</span> ON THE FLY.
            </h1>
            <p className="mt-4 max-w-xl text-[15px] opacity-90">
              ShotClassify reads the frame, calls the category, and routes the play.
              Receipts, code, stack traces, charts, chats. Confidence on every pitch.
              OCR and per-class probabilities under the hood.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Link href="/demo" className="btn btn-cue">
                Try it now
              </Link>
              <Link href="/upload" className="btn" style={{
                background: "transparent",
                color: "var(--color-chalk)",
                borderColor: "rgba(255,255,255,0.25)",
              }}>
                Ingest a frame
              </Link>
              <Link
                href="/shots"
                className="btn"
                style={{
                  background: "transparent",
                  color: "var(--color-chalk)",
                  borderColor: "rgba(255,255,255,0.25)",
                }}
              >
                Open the box score
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Stat label="Lifetime" value={total.toLocaleString()} />
            <Stat label="Classes" value="9" />
            <Stat label="P95" value="412 ms" sample />
            <Stat label="Top class" value="RECEIPT" sample />
            <Stat label="Accuracy" value="0.913" sample />
            <Stat label="ECE" value="0.041" sample />
          </div>
        </div>
      </section>

      {/* One-click live sample classifier */}
      <LiveSampleStrip />

      {/* Feed + mix */}
      <section className="grid lg:grid-cols-[2fr_1fr] gap-5">
        <Feed limit={18} />
        <aside className="panel p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="eyebrow">Category mix</span>
            {sampleMix && (
              <span className="eyebrow" style={{ color: "var(--color-cat-receipt)" }}>
                ⟂ Sample
              </span>
            )}
          </div>
          <ul className="flex flex-col gap-2">
            {CATEGORIES.map((c) => {
              const n = (mix as any)[c] ?? 0;
              const pctOfTotal = (n / mixTotal) * 100;
              return (
                <li key={c} className="grid grid-cols-[92px_1fr_56px] items-center gap-3">
                  <Chip cat={c} />
                  <div className="conf-bar">
                    <span
                      style={{
                        width: `${pctOfTotal}%`,
                        background: `var(--color-cat-${c.split("_")[0]})`,
                      }}
                    />
                  </div>
                  <span className="num text-[12px] text-right">
                    {n.toLocaleString()}
                  </span>
                </li>
              );
            })}
          </ul>

          <div className="mt-5 pt-4 border-t" style={{ borderColor: "var(--color-rule)" }}>
            <div className="eyebrow mb-2">Roster</div>
            <div className="flex flex-wrap gap-1.5">
              {CATEGORIES.map((c) => (
                <Chip key={c} cat={c} label={SHORT[c]} />
              ))}
            </div>
          </div>
        </aside>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  sample,
}: {
  label: string;
  value: string;
  sample?: boolean;
}) {
  return (
    <div
      className="rounded-sm p-3 border"
      style={{
        background: "rgba(0,0,0,0.20)",
        borderColor: "rgba(255,255,255,0.10)",
      }}
    >
      <div className="eyebrow flex items-center justify-between" style={{ color: "var(--color-chalk)", opacity: 0.7 }}>
        <span>{label}</span>
        {sample && <span style={{ color: "var(--color-cue)" }}>⟂</span>}
      </div>
      <div
        className="num mt-1"
        style={{ fontSize: 22, color: "var(--color-chalk)" }}
      >
        {value}
      </div>
    </div>
  );
}
