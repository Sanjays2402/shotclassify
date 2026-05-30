"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { SampleBadge } from "@/components/SampleBadge";
import { fetcher, ENDPOINTS } from "@/lib/api";
import {
  CATEGORIES,
  LONG,
  SHORT,
  confColor,
  ms,
  pct,
  shortId,
  type Category,
} from "@/lib/categories";
import { makeSampleShots, sampleDistribution } from "@/lib/sample";

type Detail = {
  id: string;
  filename: string;
  created_at: string;
  primary_category: Category;
  confidence: number;
  elapsed_ms?: number;
  source?: string;
  ocr_text?: string;
  image_path?: string | null;
  user_corrected_to?: Category | null;
  // Server may also include richer fields.
  classification?: {
    primary: Category;
    confidences: { category: Category; score: number }[];
    rationale?: string;
  };
  ocr?: { text: string; word_count?: number; mean_confidence?: number };
};

function fmt(iso: string) {
  return new Date(iso).toLocaleString();
}

export default function ShotDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const { data, error, isLoading } = useSWR<Detail>(
    ENDPOINTS.historyItem(id),
    fetcher
  );

  const notFound = !!error && (error as any).status === 404;
  const isSample = !data || notFound;

  // Sample fallback (clearly labeled).
  const sample = isSample
    ? (() => {
        const seed = makeSampleShots(1)[0];
        return {
          id,
          filename: seed.filename,
          created_at: seed.created_at,
          primary_category: seed.primary_category,
          confidence: seed.confidence,
          elapsed_ms: seed.elapsed_ms,
          source: seed.source,
          ocr_text: "lorem ipsum sample ocr text · this record is seeded",
        } as Detail;
      })()
    : null;

  const rec = (data ?? sample)!;
  const dist =
    rec.classification?.confidences ??
    sampleDistribution(rec.primary_category, rec.confidence);
  const sortedDist = [...dist].sort((a, b) => b.score - a.score);
  const chartData = sortedDist.map((d) => ({
    name: SHORT[d.category],
    cat: d.category,
    score: +(d.score * 100).toFixed(2),
  }));

  if (isLoading && !rec) {
    return <div className="p-6 text-sm opacity-70">Cueing up the replay…</div>;
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3 text-[12px]">
        <Link href="/shots" className="eyebrow hover:underline">
          ← All shots
        </Link>
        <span className="opacity-40">/</span>
        <span className="num">{shortId(rec.id)}</span>
        {isSample && <SampleBadge note="No record found; rendering seeded sample." />}
      </div>

      <header className="panel p-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">The call</div>
          <div className="flex items-center gap-3 mt-1">
            <Chip cat={rec.primary_category} size="lg" />
            <span
              className="num text-[28px]"
              style={{ color: confColor(rec.confidence) }}
            >
              {pct(rec.confidence, 1)}
            </span>
          </div>
          <h1 className="h-display text-[24px] mt-3 truncate max-w-[60ch]">
            {rec.filename}
          </h1>
          <div className="num text-[11px] opacity-70 mt-1">
            {fmt(rec.created_at)} · {rec.source ?? "api"} ·{" "}
            {rec.elapsed_ms != null ? ms(rec.elapsed_ms) : "latency n/a"}
          </div>
        </div>
        {rec.user_corrected_to && (
          <div className="text-right">
            <div className="eyebrow">Corrected to</div>
            <Chip cat={rec.user_corrected_to} />
          </div>
        )}
      </header>

      <section className="grid lg:grid-cols-[1.4fr_1fr] gap-5">
        <div className="panel p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="eyebrow">Confidence distribution</span>
            <span className="num text-[11px] opacity-60">{CATEGORIES.length} classes</span>
          </div>
          <div style={{ width: "100%", height: 280 }}>
            {mounted && (
            <ResponsiveContainer>
              <BarChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                <CartesianGrid stroke="rgba(11,15,12,0.08)" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
                  stroke="rgba(11,15,12,0.4)"
                />
                <YAxis
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
                  stroke="rgba(11,15,12,0.4)"
                  domain={[0, 100]}
                  unit="%"
                />
                <Tooltip
                  cursor={{ fill: "rgba(14,92,58,0.06)" }}
                  contentStyle={{
                    background: "var(--color-ink)",
                    border: "1px solid #000",
                    borderRadius: 3,
                    color: "var(--color-chalk)",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                  }}
                  formatter={(v: any) => [`${v}%`, "score"]}
                />
                <Bar dataKey="score" radius={[2, 2, 0, 0]}>
                  {chartData.map((d) => (
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

          <ul className="mt-4 flex flex-col gap-1.5">
            {sortedDist.map((d) => (
              <li
                key={d.category}
                className="grid grid-cols-[110px_1fr_64px] items-center gap-3"
              >
                <Chip cat={d.category} />
                <div style={{ ["--bar" as any]: `var(--color-cat-${d.category.split("_")[0]})` }}>
                  <ConfBar score={d.score} />
                </div>
                <span className="num text-[12px] text-right">{pct(d.score, 2)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex flex-col gap-5">
          <div className="panel p-5">
            <div className="eyebrow mb-2">OCR transcript</div>
            <pre className="text-[12px] whitespace-pre-wrap leading-snug max-h-[260px] overflow-auto">
{rec.ocr?.text || rec.ocr_text || "(no OCR text on record)"}
            </pre>
            {rec.ocr?.word_count != null && (
              <div className="num text-[10px] opacity-60 mt-2">
                {rec.ocr.word_count} words · mean conf{" "}
                {rec.ocr.mean_confidence?.toFixed?.(2) ?? "n/a"}
              </div>
            )}
          </div>

          <div className="panel-dark p-5">
            <div className="eyebrow mb-2" style={{ color: "var(--color-chalk)" }}>
              Rationale
            </div>
            <p className="text-[12px] opacity-90 leading-relaxed">
              {rec.classification?.rationale ||
                "The model called this class on visual layout, density, and OCR cues. No verbal rationale on file for this record."}
            </p>
          </div>

          {rec.image_path && (
            <div className="panel p-3">
              <div className="eyebrow mb-2">Frame</div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/api/proxy/blob/${rec.image_path.split("/").pop()}`}
                alt={rec.filename}
                className="w-full rounded-sm"
              />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
