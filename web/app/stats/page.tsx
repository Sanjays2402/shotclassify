"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartLineUp,
  Gauge,
  Stack,
  Timer,
  PencilSimple,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { CategoryLegendChip } from "@/components/CategoryLegendChip";
import { StatInfoPopover } from "@/components/StatInfoPopover";
import { SampleBadge } from "@/components/SampleBadge";
import { useChartTheme } from "@/components/useChartTheme";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { CATEGORIES, LONG, SHORT, ms, pct, type Category } from "@/lib/categories";
import { categoryLegendSummary, totalCount } from "@/lib/category-legend";

type Aggregate = {
  total: number;
  window_hours: number;
  window_count: number;
  corrections: number;
  correction_rate: number;
  mean_confidence: number;
  latency_ms: { p50: number; p95: number; p99: number; count: number };
  per_class: { category: Category; count: number; mean_confidence: number }[];
  confidence_histogram: { bin: number; lo: number; hi: number; count: number }[];
  hourly: { hour: string; count: number }[];
};

const WINDOWS = [
  { label: "24h", h: 24 },
  { label: "7d", h: 24 * 7 },
  { label: "30d", h: 24 * 30 },
];

function sampleAggregate(hours: number): Aggregate {
  // Deterministic seeded sample so first-time visitors see something live.
  const seed = (n: number) => ((n * 9301 + 49297) % 233280) / 233280;
  const per_class = CATEGORIES.map((c, i) => ({
    category: c,
    count: Math.floor(seed(i + 3) * 80) + 6,
    mean_confidence: 0.55 + seed(i + 11) * 0.4,
  })).sort((a, b) => b.count - a.count);
  const total = per_class.reduce((a, b) => a + b.count, 0);
  const buckets = Math.min(hours, 48);
  const hourly = Array.from({ length: buckets }, (_, i) => {
    const d = new Date(Date.now() - (buckets - 1 - i) * 3600 * 1000);
    d.setMinutes(0, 0, 0);
    return { hour: d.toISOString(), count: Math.floor(seed(i + 17) * 9) + 1 };
  });
  const conf_hist = Array.from({ length: 10 }, (_, i) => ({
    bin: i,
    lo: i / 10,
    hi: (i + 1) / 10,
    count: Math.floor(seed(i + 31) * 40 * (i >= 6 ? 2 : 1)),
  }));
  return {
    total,
    window_hours: hours,
    window_count: hourly.reduce((a, b) => a + b.count, 0),
    corrections: Math.floor(total * 0.06),
    correction_rate: 0.06,
    mean_confidence: 0.78,
    latency_ms: { p50: 320, p95: 412, p99: 540, count: total },
    per_class,
    confidence_histogram: conf_hist,
    hourly,
  };
}

function fmtHour(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit" });
}

function Stat({
  label,
  value,
  hint,
  icon,
  info,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: React.ReactNode;
  info?: React.ReactNode;
}) {
  return (
    <div className="panel p-4 flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="eyebrow flex items-center gap-1.5">
          {label}
          {info}
        </span>
        <span className="opacity-60">{icon}</span>
      </div>
      <div className="num text-[24px]">{value}</div>
      {hint && <div className="num text-[10px] opacity-60">{hint}</div>}
    </div>
  );
}

export default function StatsPage() {
  const [hours, setHours] = useState(24);
  const [mounted, setMounted] = useState(false);
  const ct = useChartTheme();
  useEffect(() => setMounted(true), []);

  const { data, error, isLoading } = useSWR<Aggregate>(
    ENDPOINTS.aggregate(hours),
    fetcher,
    { refreshInterval: 30_000 }
  );

  const live = !!data && !error && data.total > 0;
  const agg = live ? data! : sampleAggregate(hours);
  const perClassTotal = totalCount(agg.per_class);

  const perClassChart = agg.per_class.map((d) => ({
    name: SHORT[d.category],
    cat: d.category,
    count: d.count,
    mean: +(d.mean_confidence * 100).toFixed(1),
  }));
  const confHistChart = agg.confidence_histogram.map((d) => ({
    name: `${Math.round(d.lo * 100)}-${Math.round(d.hi * 100)}`,
    count: d.count,
    bin: d.bin,
  }));
  const hourlyChart = agg.hourly.map((d) => ({
    name: fmtHour(d.hour),
    count: d.count,
  }));

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Analytics</div>
          <h1 className="h-display text-[32px] md:text-[40px]">Box score</h1>
          <p className="text-[13px] opacity-80 mt-1 max-w-xl">
            Real rollups from the classification store. Per class volume, calibration,
            latency, and ingest tempo over the selected window.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {WINDOWS.map((w) => (
            <button
              key={w.h}
              type="button"
              onClick={() => setHours(w.h)}
              aria-pressed={hours === w.h}
              className="btn text-[12px] px-3 py-1.5"
              style={{
                background:
                  hours === w.h ? "var(--color-felt)" : "transparent",
                color:
                  hours === w.h ? "var(--color-chalk)" : "var(--color-ink)",
                borderColor: "var(--color-rule)",
              }}
            >
              {w.label}
            </button>
          ))}
          {!live && <SampleBadge note="Seeded preview until you ingest data." />}
        </div>
      </header>

      {error && (
        <div
          className="panel p-3 flex items-center gap-2 text-[12px]"
          style={{ color: "var(--color-conf-low)" }}
        >
          <Warning weight="duotone" size={16} />
          Couldn&apos;t reach the API. Showing a seeded preview.
        </div>
      )}

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat
          label="Lifetime shots"
          value={agg.total.toLocaleString()}
          hint={`${agg.window_count.toLocaleString()} in window`}
          icon={<Stack weight="duotone" size={18} />}
          info={<StatInfoPopover stat="lifetime" hours={hours} />}
        />
        <Stat
          label="Mean confidence"
          value={pct(agg.mean_confidence, 1)}
          hint={`${agg.latency_ms.count} timed`}
          icon={<Gauge weight="duotone" size={18} />}
          info={<StatInfoPopover stat="mean_confidence" hours={hours} />}
        />
        <Stat
          label="P95 latency"
          value={ms(agg.latency_ms.p95)}
          hint={`p50 ${ms(agg.latency_ms.p50)} · p99 ${ms(agg.latency_ms.p99)}`}
          icon={<Timer weight="duotone" size={18} />}
          info={<StatInfoPopover stat="p95_latency" hours={hours} />}
        />
        <Stat
          label="Corrections"
          value={agg.corrections.toLocaleString()}
          hint={`${pct(agg.correction_rate, 1)} rate`}
          icon={<PencilSimple weight="duotone" size={18} />}
          info={<StatInfoPopover stat="corrections" hours={hours} />}
        />
      </section>

      <section className="panel p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="eyebrow flex items-center gap-1.5">
            <ChartLineUp weight="duotone" size={14} /> Ingest tempo
          </span>
          <span className="num text-[11px] opacity-60">last {agg.window_hours}h</span>
        </div>
        <div style={{ width: "100%", height: 220 }}>
          {mounted && (
            <ResponsiveContainer>
              <AreaChart data={hourlyChart} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
                <defs>
                  <linearGradient id="tempo" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-felt)" stopOpacity={0.55} />
                    <stop offset="100%" stopColor="var(--color-felt)" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={ct.gridStroke} vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                  stroke={ct.axisStroke}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                  stroke={ct.axisStroke}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: ct.cursorFill }}
                  contentStyle={ct.tooltip}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="var(--color-felt)"
                  strokeWidth={2}
                  fill="url(#tempo)"
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
        {hourlyChart.length === 0 && (
          <div className="text-[12px] opacity-60 num text-center py-6">
            No shots in this window yet.
          </div>
        )}
      </section>

      <section className="grid lg:grid-cols-2 gap-5">
        <div className="panel p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="eyebrow">Class mix</span>
            <span className="num text-[11px] opacity-60">{agg.per_class.length} classes seen</span>
          </div>
          <div style={{ width: "100%", height: 240 }}>
            {mounted && (
              <ResponsiveContainer>
                <BarChart
                  data={perClassChart}
                  margin={{ top: 8, right: 12, left: 0, bottom: 8 }}
                >
                  <CartesianGrid stroke={ct.gridStroke} vertical={false} />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                    stroke={ct.axisStroke}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                    stroke={ct.axisStroke}
                    allowDecimals={false}
                  />
                  <Tooltip
                    cursor={{ fill: ct.cursorFill }}
                    contentStyle={ct.tooltip}
                  />
                  <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                    {perClassChart.map((d) => (
                      <Cell
                        key={d.cat}
                        fill={`var(--color-cat-${d.cat.split("_")[0]})`}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <ul className="mt-3 flex flex-col gap-1.5">
            {agg.per_class.map((d) => (
              <li
                key={d.category}
                className="grid grid-cols-[120px_1fr_64px_64px] items-center gap-3 text-[12px]"
              >
                <CategoryLegendChip
                  summary={categoryLegendSummary(d, perClassTotal)}
                />
                <div
                  className="h-1.5 rounded-sm overflow-hidden"
                  style={{ background: "rgba(11,15,12,0.08)" }}
                >
                  <div
                    className="h-full"
                    style={{
                      width: `${Math.min(100, (d.count / (agg.per_class[0]?.count || 1)) * 100)}%`,
                      background: `var(--color-cat-${d.category.split("_")[0]})`,
                    }}
                  />
                </div>
                <span className="num text-right">{d.count}</span>
                <span className="num text-right opacity-70">
                  {pct(d.mean_confidence, 0)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="panel p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="eyebrow">Confidence calibration</span>
            <span className="num text-[11px] opacity-60">10 bins · 0 to 100%</span>
          </div>
          <div style={{ width: "100%", height: 240 }}>
            {mounted && (
              <ResponsiveContainer>
                <BarChart
                  data={confHistChart}
                  margin={{ top: 8, right: 12, left: 0, bottom: 8 }}
                >
                  <CartesianGrid stroke={ct.gridStroke} vertical={false} />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                    stroke={ct.axisStroke}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                    stroke={ct.axisStroke}
                    allowDecimals={false}
                  />
                  <Tooltip
                    cursor={{ fill: ct.cursorFill }}
                    contentStyle={ct.tooltip}
                  />
                  <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                    {confHistChart.map((d) => (
                      <Cell
                        key={d.bin}
                        fill={
                          d.bin >= 8
                            ? "var(--color-conf-high)"
                            : d.bin >= 5
                              ? "var(--color-conf-mid)"
                              : "var(--color-conf-low)"
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <p className="text-[11px] opacity-70 mt-3 leading-relaxed">
            A healthy classifier shows a right-leaning distribution. Heavy mass under
            55% suggests the model hedges, which raises router rejection rate.
          </p>
        </div>
      </section>

      <section className="panel p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="eyebrow">All classes</span>
          <Link href="/shots" className="text-[12px] hover:underline">
            Open shots →
          </Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {CATEGORIES.map((c) => {
            const row = agg.per_class.find((p) => p.category === c);
            const count = row?.count ?? 0;
            const mean = row?.mean_confidence ?? 0;
            return (
              <Link
                key={c}
                href={`/shots?category=${c}`}
                className="panel p-3 hover:shadow-md transition-shadow"
              >
                <Chip cat={c} />
                <div className="num text-[20px] mt-2">{count.toLocaleString()}</div>
                <div className="num text-[10px] opacity-60">
                  {LONG[c]} · {pct(mean, 0)} avg
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {isLoading && !data && (
        <div className="text-[12px] opacity-60 num">Pulling rollups…</div>
      )}
    </div>
  );
}
