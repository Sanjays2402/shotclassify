"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ComposedChart,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
} from "recharts";
import { SampleBadge } from "@/components/SampleBadge";
import { sampleReliability } from "@/lib/sample";

export default function CalibrationPage() {
  const data = useMemo(() => sampleReliability(), []);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Expected Calibration Error.
  const total = data.reduce((a, b) => a + b.n, 0);
  const ece =
    data.reduce((a, b) => a + (b.n / total) * Math.abs(b.acc - b.conf), 0);

  const brier = 0.072; // placeholder until exposed by API
  const logloss = 0.281;

  const chart = data.map((d) => ({
    conf: +(d.conf * 100).toFixed(0),
    acc: +(d.acc * 100).toFixed(1),
    n: d.n,
  }));

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="eyebrow">Replay booth</div>
          <h1 className="h-display text-[34px]">CALIBRATION</h1>
          <p className="text-[13px] opacity-70 mt-1 max-w-[60ch]">
            Does the model mean what it says? Reliability diagram plots predicted confidence against
            empirical accuracy across binned predictions. The diagonal is perfect calibration.
          </p>
        </div>
        <SampleBadge note="Reliability metrics are not yet exposed by the API; figures shown are seeded." />
      </header>

      <section className="grid lg:grid-cols-[2fr_1fr] gap-5">
        <div className="panel p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="eyebrow">Reliability diagram</span>
            <span className="num text-[11px] opacity-60">{data.length} bins · n={total}</span>
          </div>
          <div style={{ width: "100%", height: 340 }}>
            {mounted && (
            <ResponsiveContainer>
              <ComposedChart data={chart} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid stroke="rgba(11,15,12,0.08)" />
                <XAxis
                  dataKey="conf"
                  type="number"
                  domain={[0, 100]}
                  tickCount={11}
                  unit="%"
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
                  stroke="rgba(11,15,12,0.5)"
                  label={{
                    value: "Predicted confidence",
                    position: "insideBottom",
                    offset: -2,
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    fill: "rgba(11,15,12,0.6)",
                  }}
                />
                <YAxis
                  yAxisId="left"
                  domain={[0, 100]}
                  tickCount={6}
                  unit="%"
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
                  stroke="rgba(11,15,12,0.5)"
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
                  stroke="rgba(11,15,12,0.3)"
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--color-ink)",
                    border: "1px solid #000",
                    borderRadius: 3,
                    color: "var(--color-chalk)",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                  }}
                />
                <ReferenceLine
                  yAxisId="left"
                  segment={[
                    { x: 0, y: 0 },
                    { x: 100, y: 100 },
                  ]}
                  stroke="rgba(11,15,12,0.35)"
                  strokeDasharray="3 3"
                />
                <Bar
                  yAxisId="right"
                  dataKey="n"
                  fill="rgba(14,92,58,0.15)"
                  barSize={18}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="acc"
                  stroke="var(--color-cue)"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "var(--color-cue)" }}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
            )}
          </div>
          <div className="num text-[11px] opacity-60 mt-2">
            Yellow line: empirical accuracy per bin. Faint bars: sample volume per bin (right axis).
            Dashed: y = x.
          </div>
        </div>

        <div className="flex flex-col gap-5">
          <Metric label="ECE" value={ece.toFixed(4)} hint="Expected Calibration Error. Lower is sharper." />
          <Metric label="Brier" value={brier.toFixed(3)} hint="Mean squared error between confidence and outcome." />
          <Metric label="Log loss" value={logloss.toFixed(3)} hint="Cross-entropy on holdout." />
          <Metric label="Top-1 accuracy" value="91.3%" hint="Holdout: 3,420 frames." />
        </div>
      </section>

      <section className="panel p-5">
        <div className="eyebrow mb-2">Reading the chart</div>
        <p className="text-[13px] opacity-80 max-w-[70ch]">
          Points above the dashed line mean the model is underconfident in that bin: it called the
          play softer than it should have. Points below mean overconfident, the riskier failure mode.
          Drift the high-confidence bins (0.85 and 0.95) below the line and downstream auto-routing
          will start misfiring.
        </p>
      </section>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="panel p-4">
      <div className="eyebrow">{label}</div>
      <div className="num text-[28px] mt-1">{value}</div>
      <div className="text-[11px] opacity-70 mt-1">{hint}</div>
    </div>
  );
}
