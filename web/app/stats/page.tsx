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
  Line,
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
import { Skeleton } from "@/components/Skeleton";
import { useChartTheme } from "@/components/useChartTheme";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { CATEGORIES, LONG, SHORT, ms, pct, type Category } from "@/lib/categories";
import { categoryLegendSummary, totalCount } from "@/lib/category-legend";
import {
  readStatsWindow,
  writeStatsWindow,
  labelForStatsWindow,
  nextStatsWindow,
  STATS_WINDOWS,
  STATS_WINDOW_DEFAULT,
  type StatsWindowHours,
} from "@/lib/stats-window";
import { chartsBusy } from "@/lib/stats-loading";
import { statsClassLink } from "@/lib/stats-class-link";
import { classMixTooltipFormatter } from "@/lib/class-mix-tooltip";
import { kpiSkeletonKeys, showKpiSkeleton } from "@/lib/kpi-skeleton";
import { confTrend, confTrendDeltaLabel } from "@/lib/conf-trend";
import { compactNumber, fullNumber, isCompacted } from "@/lib/num-compact";

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
  hourly: { hour: string; count: number; mean_confidence: number }[];
};

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
    return { hour: d.toISOString(), count: Math.floor(seed(i + 17) * 9) + 1, mean_confidence: 0.6 + seed(i + 23) * 0.35 };
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
  titleAttr,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: React.ReactNode;
  info?: React.ReactNode;
  // Exact figure tooltip when `value` is an abbreviated count, so the compact
  // KPI never hides the real number from a hover (or assistive tech reading it).
  titleAttr?: string;
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
      <div className="num text-[24px]" title={titleAttr}>{value}</div>
      {hint && <div className="num text-[10px] opacity-60">{hint}</div>}
    </div>
  );
}

// Loading placeholder for a single KPI card (F146) -- matches Stat's panel p-4
// footprint with chalk skeleton lines so the four cards settle in lockstep
// with the chart skeletons rather than popping in fully formed.
function StatSkeleton() {
  return (
    <div className="panel p-4 flex flex-col gap-1" data-testid="kpi-skeleton">
      <div className="flex items-center justify-between">
        <Skeleton width={88} height={11} radius={2} className="opacity-70" />
        <Skeleton variant="circle" width={18} height={18} className="opacity-50" />
      </div>
      <Skeleton width={72} height={26} radius={4} className="opacity-70 mt-1" />
      <Skeleton width={120} height={9} radius={2} className="opacity-50 mt-1" />
    </div>
  );
}

export default function StatsPage() {
  const [hours, setHours] = useState<StatsWindowHours>(STATS_WINDOW_DEFAULT);
  const [mounted, setMounted] = useState(false);
  // Captured once on mount so the class-tile deep-links (F60) have a stable
  // `now` reference and don't recompute their since= date every render.
  const [now, setNow] = useState(0);
  const ct = useChartTheme();
  useEffect(() => {
    setMounted(true);
    setNow(Date.now());
  }, []);

  // Reopen on the window the user last chose (F44). SSR can't know it, so we
  // read on mount; an invalid / missing value coerces back to the default.
  useEffect(() => {
    setHours(readStatsWindow());
  }, []);

  // Persisting setter for the window buttons -- updates state and remembers
  // the choice so a return visit lands on the same scope.
  const pickWindow = (h: StatsWindowHours) => {
    setHours(h);
    writeStatsWindow(h);
  };

  // "w" cycles the time window (24h -> 7d -> 30d), mirroring the shots-list
  // `v` (view) / `d` (density) shortcuts and registered under a new "stats"
  // scope in the ? overlay. Two guards beyond the usual input/modifier checks
  // (F79):
  //   1. Input guard -- never fire while a field is focused.
  //   2. Chord guard -- `g w` is the "go to Webhooks" section chord (F61). The
  //      keystroke that completes it also reaches this bare-`w` handler, so we
  //      skip a `w` that lands within the chord window after a `g`, letting
  //      HotKeys own the navigation without us flipping the window on the way
  //      out. Same shape as the shots page's `d` vs `g d` guard.
  useEffect(() => {
    let lastGAt = 0;
    const CHORD_WINDOW_MS = 1200; // matches createSequenceTracker's default
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      const k = e.key.toLowerCase();
      if (k === "g") {
        lastGAt = e.timeStamp || performance.now();
        return;
      }
      if (k !== "w") return;
      // Tail of the `g w` chord -> let HotKeys navigate; don't cycle.
      const now = e.timeStamp || performance.now();
      if (now - lastGAt <= CHORD_WINDOW_MS) {
        lastGAt = 0;
        return;
      }
      e.preventDefault();
      setHours((cur) => {
        const next = nextStatsWindow(cur);
        writeStatsWindow(next);
        return next;
      });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const { data, error, isLoading } = useSWR<Aggregate>(
    ENDPOINTS.aggregate(hours),
    fetcher,
    { refreshInterval: 30_000 }
  );

  const live = !!data && !error && data.total > 0;
  const agg = live ? data! : sampleAggregate(hours);
  const perClassTotal = totalCount(agg.per_class);

  // Short window label ("24h" / "7d" / "30d") threaded into each KPI card's
  // sub-label (F106) so the scope of every stat is unambiguous at a glance --
  // the cards previously said "in window" / bare rates without naming it.
  const winLabel = labelForStatsWindow(hours);

  // Show chart skeletons before mount or while the very first aggregate is
  // still loading with nothing to draw yet (F37). `data` is the real SWR
  // payload -- once it (or the seeded fallback after an error) is available
  // we render the charts. `error` short-circuits to the seeded preview, so
  // it counts as "have something to draw".
  const busy = chartsBusy(mounted, isLoading, !!data || !!error);

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
    conf: +(d.mean_confidence * 100).toFixed(1),
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
          {STATS_WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => pickWindow(w)}
              aria-pressed={hours === w}
              title={`Show the last ${labelForStatsWindow(w)} (press W to cycle)`}
              className="btn text-[12px] px-3 py-1.5"
              style={{
                background:
                  hours === w ? "var(--color-felt)" : "transparent",
                color:
                  hours === w ? "var(--color-chalk)" : "var(--color-ink)",
                borderColor: "var(--color-rule)",
              }}
            >
              {labelForStatsWindow(w)}
            </button>
          ))}
          {/* Faint visible "W" hint so the keyboard cycle (F79) is discoverable
              on the page, not just in the ? overlay -- mirrors how F81 surfaces
              [ ] on ShotNav. Hidden < sm to keep the header compact; aria-hidden
              because the buttons' titles already spell out "press W to cycle". */}
          <span
            className="hidden sm:inline-flex items-center gap-1 opacity-45 select-none"
            aria-hidden
            title="Press W to cycle the window"
          >
            <kbd className="kbd text-[10px] leading-none">W</kbd>
            <span className="num text-[10px] uppercase tracking-wider">
              cycle
            </span>
          </span>
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
        {showKpiSkeleton(busy)
          ? kpiSkeletonKeys().map((k) => <StatSkeleton key={k} />)
          : (
        <>
        <Stat
          label="Lifetime shots"
          value={compactNumber(agg.total)}
          titleAttr={isCompacted(agg.total) ? `${fullNumber(agg.total)} shots` : undefined}
          hint={`${agg.window_count.toLocaleString()} in last ${winLabel}`}
          icon={<Stack weight="duotone" size={18} />}
          info={<StatInfoPopover stat="lifetime" hours={hours} />}
        />
        <Stat
          label="Mean confidence"
          value={pct(agg.mean_confidence, 1)}
          hint={(() => {
            // Per-hour mean-confidence trend across the window (F65). Reads the
            // first/last populated buckets; appends a signed pts delta so the
            // KPI says which way calibration is drifting, not just the snapshot.
            const t = confTrend(agg.hourly);
            const d = confTrendDeltaLabel(t);
            return d ? `${agg.latency_ms.count} timed · ${d} · last ${winLabel}` : `${agg.latency_ms.count} timed · last ${winLabel}`;
          })()}
          icon={<Gauge weight="duotone" size={18} />}
          info={<StatInfoPopover stat="mean_confidence" hours={hours} />}
        />
        <Stat
          label="P95 latency"
          value={ms(agg.latency_ms.p95)}
          hint={`p50 ${ms(agg.latency_ms.p50)} · p99 ${ms(agg.latency_ms.p99)} · last ${winLabel}`}
          icon={<Timer weight="duotone" size={18} />}
          info={<StatInfoPopover stat="p95_latency" hours={hours} />}
        />
        <Stat
          label="Corrections"
          value={compactNumber(agg.corrections)}
          titleAttr={isCompacted(agg.corrections) ? `${fullNumber(agg.corrections)} corrections` : undefined}
          hint={`${pct(agg.correction_rate, 1)} rate · last ${winLabel}`}
          icon={<PencilSimple weight="duotone" size={18} />}
          info={<StatInfoPopover stat="corrections" hours={hours} />}
        />
        </>
        )}
      </section>

      <section className="panel p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="eyebrow flex items-center gap-1.5">
            <ChartLineUp weight="duotone" size={14} /> Ingest tempo
          </span>
          <span className="flex items-center gap-3">
            <span
              className="hidden sm:inline-flex items-center gap-1 text-[10px] uppercase tracking-wider opacity-60"
              title="Mean classifier confidence per hour, plotted against the right axis"
            >
              <span
                aria-hidden
                style={{
                  width: 14,
                  borderTop: "1.5px dashed var(--color-conf-high, #0E5C3A)",
                  display: "inline-block",
                }}
              />
              conf
            </span>
            <span className="num text-[11px] opacity-60">last {agg.window_hours}h</span>
          </span>
        </div>
        <div style={{ width: "100%", height: 220 }}>
          {busy ? (
            <Skeleton height="100%" radius={6} className="opacity-70" />
          ) : (
            mounted && (
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
                  yAxisId="vol"
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                  stroke={ct.axisStroke}
                  allowDecimals={false}
                />
                <YAxis
                  yAxisId="conf"
                  orientation="right"
                  domain={[0, 100]}
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: ct.tickFill }}
                  stroke={ct.axisStrokeFaint}
                  width={28}
                  tickFormatter={(v: number) => `${v}%`}
                />
                <Tooltip
                  cursor={{ fill: ct.cursorFill }}
                  contentStyle={ct.tooltip}
                  formatter={(val, name) =>
                    String(name) === "conf"
                      ? [`${val}%`, "Mean conf"]
                      : [String(val), "Shots"]
                  }
                />
                <Area
                  yAxisId="vol"
                  type="monotone"
                  dataKey="count"
                  stroke="var(--color-felt)"
                  strokeWidth={2}
                  fill="url(#tempo)"
                />
                <Line
                  yAxisId="conf"
                  type="monotone"
                  dataKey="conf"
                  stroke={ct.positiveStroke}
                  strokeWidth={1.5}
                  strokeDasharray="3 3"
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
            )
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
            {busy ? (
              <Skeleton height="100%" radius={6} className="opacity-70" />
            ) : (
              mounted && (
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
                    formatter={(val, _name, p) =>
                      classMixTooltipFormatter(Number(val), p?.payload)
                    }
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
              )
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
            {busy ? (
              <Skeleton height="100%" radius={6} className="opacity-70" />
            ) : (
              mounted && (
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
              )
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
            // Carry the active window into the link as a since= date so the
            // tile lands on /shots pre-filtered to this class AND timeframe
            // (F60). Pre-mount we keep the bare class link so SSR and the
            // first client render agree; post-mount it upgrades to the
            // windowed deep-link once `now` is captured.
            const href =
              mounted && now > 0
                ? statsClassLink(c, hours, now)
                : `/shots?category=${c}`;
            return (
              <Link
                key={c}
                href={href}
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

      {busy && (
        <div className="text-[12px] opacity-60 num" role="status" aria-live="polite">
          Pulling rollups…
        </div>
      )}
    </div>
  );
}
