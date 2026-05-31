"use client";

import { useCallback, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
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
import { Lightning, Sparkle, Image as ImageIcon, Warning } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { confColor, LONG, ms, pct, type Category } from "@/lib/categories";

type Confidence = { category: Category; score: number };

type Result = {
  id: string;
  filename: string;
  classification: {
    primary: Category;
    confidences: Confidence[];
    rationale?: string;
  };
  ocr?: { text?: string };
  elapsed_ms?: number;
};

type Sample = {
  slug: string;
  title: string;
  blurb: string;
  expected: Category;
  src: string;
};

const SAMPLES: Sample[] = [
  {
    slug: "receipt",
    title: "Coffee shop receipt",
    blurb: "Itemised receipt with totals, tax, and a tip line.",
    expected: "receipt",
    src: "/samples/fake-receipt.png",
  },
  {
    slug: "code",
    title: "Python snippet",
    blurb: "A short function with syntax highlighting from an IDE.",
    expected: "code_snippet",
    src: "/samples/fake-code.png",
  },
  {
    slug: "error",
    title: "Stack trace",
    blurb: "A traceback from a failing test run with file paths.",
    expected: "error_stacktrace",
    src: "/samples/fake-error.png",
  },
  {
    slug: "chat",
    title: "Group chat",
    blurb: "A messaging UI with avatars, timestamps, and bubbles.",
    expected: "chat_screenshot",
    src: "/samples/fake-chat.png",
  },
];

export default function DemoPage() {
  const [activeSlug, setActiveSlug] = useState<string>(SAMPLES[0].slug);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = useMemo(
    () => SAMPLES.find((s) => s.slug === activeSlug) ?? SAMPLES[0],
    [activeSlug]
  );

  const runSample = useCallback(async (sample: Sample) => {
    setActiveSlug(sample.slug);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const blob = await fetch(sample.src).then((r) => {
        if (!r.ok) throw new Error(`could not load ${sample.src}`);
        return r.blob();
      });
      const file = new File([blob], `${sample.slug}.png`, { type: blob.type || "image/png" });
      const fd = new FormData();
      fd.append("file", file);
      const t0 = performance.now();
      const res = await fetch("/api/classify", { method: "POST", body: fd });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `${res.status} ${res.statusText}`);
      }
      const json = (await res.json()) as Result;
      if (json.elapsed_ms == null) json.elapsed_ms = Math.round(performance.now() - t0);
      setResult(json);
    } catch (e: any) {
      setError(e?.message ?? "Classification failed.");
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Sparkle weight="duotone" size={18} />
          <span className="eyebrow">Demo</span>
        </div>
        <h1 className="h-display text-[34px] md:text-[44px]">TRY IT IN ONE CLICK</h1>
        <p className="max-w-2xl text-[14px] opacity-80">
          Pick a sample screenshot. We run it through the same OCR plus vision pipeline used
          in production and show the class probabilities, the model rationale, and the OCR
          transcript. No upload, no signup.
        </p>
      </header>

      <section
        className="rounded-2xl border p-3 md:p-4"
        style={{ borderColor: "var(--color-rule)", background: "var(--color-chalk)" }}
      >
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {SAMPLES.map((s) => {
            const selected = s.slug === activeSlug;
            return (
              <button
                key={s.slug}
                onClick={() => runSample(s)}
                disabled={busy}
                aria-pressed={selected}
                className="group text-left rounded-xl border overflow-hidden focus:outline-none focus:ring-2 transition-shadow disabled:opacity-60"
                style={{
                  borderColor: selected ? "var(--color-felt)" : "var(--color-rule)",
                  boxShadow: selected ? "0 0 0 2px var(--color-felt) inset" : undefined,
                  background: "white",
                }}
              >
                <div
                  className="relative aspect-[4/3] overflow-hidden"
                  style={{ background: "var(--color-paper)" }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={s.src}
                    alt={s.title}
                    className="absolute inset-0 w-full h-full object-cover transition-transform group-hover:scale-[1.02]"
                  />
                </div>
                <div className="p-3 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium">{s.title}</span>
                    <Chip cat={s.expected} />
                  </div>
                  <span className="text-[11px] opacity-70">{s.blurb}</span>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <section className="grid md:grid-cols-[1.1fr_1fr] gap-4">
        <div
          className="rounded-2xl border overflow-hidden"
          style={{ borderColor: "var(--color-rule)", background: "white" }}
        >
          <div
            className="px-4 py-3 border-b flex items-center justify-between"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="flex items-center gap-2">
              <ImageIcon weight="duotone" size={16} />
              <span className="eyebrow">Input</span>
            </div>
            <span className="text-[12px] opacity-70">{active.title}</span>
          </div>
          <div
            className="relative aspect-[4/3]"
            style={{ background: "var(--color-paper)" }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={active.src}
              alt={active.title}
              className="absolute inset-0 w-full h-full object-contain"
            />
          </div>
        </div>

        <div
          className="rounded-2xl border p-4 flex flex-col gap-4"
          style={{ borderColor: "var(--color-rule)", background: "white" }}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Lightning weight="duotone" size={16} />
              <span className="eyebrow">Prediction</span>
            </div>
            <button
              onClick={() => runSample(active)}
              disabled={busy}
              className="btn btn-cue text-[12px] px-3 py-1.5 disabled:opacity-60"
            >
              {busy ? "Running" : "Run again"}
            </button>
          </div>

          {error && (
            <div
              className="rounded-lg border px-3 py-2 flex items-start gap-2 text-[12px]"
              style={{ borderColor: "var(--color-conf-low)", color: "var(--color-conf-low)" }}
            >
              <Warning weight="duotone" size={16} />
              <div>
                <div className="font-medium">Classifier unreachable.</div>
                <div className="opacity-80 break-all">{error}</div>
                <div className="mt-1 opacity-70">
                  Start the API with <span className="font-mono">make api</span>, then retry.
                </div>
              </div>
            </div>
          )}

          {busy && !result && <ResultSkeleton />}

          {result && !busy && <ResultPanel result={result} />}

          {!busy && !result && !error && (
            <div className="text-[13px] opacity-70">
              Pick a sample above to see the model predictions.
            </div>
          )}
        </div>
      </section>

      <section className="text-[12px] opacity-70">
        Want to test your own screenshot? Head to{" "}
        <Link href="/upload" className="underline">
          /upload
        </Link>
        .
      </section>
    </div>
  );
}

function ResultPanel({ result }: { result: Result }) {
  const conf = result.classification.confidences ?? [];
  const sorted = [...conf].sort((a, b) => b.score - a.score);
  const primary = result.classification.primary;
  const top = sorted[0];
  const chartData = sorted.map((c) => ({
    name: LONG[c.category] ?? c.category,
    score: Number((c.score * 100).toFixed(2)),
    category: c.category,
    isPrimary: c.category === primary,
  }));
  const ocrText = result.ocr?.text?.trim();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <div className="eyebrow">Primary</div>
          <div className="h-display text-[28px]">{LONG[primary] ?? primary}</div>
        </div>
        <div className="text-right">
          <div className="eyebrow">Confidence</div>
          <div
            className="h-display text-[28px]"
            style={{ color: top ? confColor(top.score) : undefined }}
          >
            {top ? pct(top.score, 1) : "n/a"}
          </div>
        </div>
        <div className="text-right">
          <div className="eyebrow">Latency</div>
          <div className="h-display text-[28px]">
            {result.elapsed_ms != null ? ms(result.elapsed_ms) : "n/a"}
          </div>
        </div>
      </div>

      <div
        className="h-[260px] rounded-lg border p-2"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 6, right: 18, bottom: 6, left: 10 }}
          >
            <CartesianGrid horizontal={false} stroke="var(--color-rule)" strokeDasharray="2 4" />
            <XAxis
              type="number"
              domain={[0, 100]}
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => `${v}%`}
              stroke="var(--color-rule)"
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 11 }}
              width={96}
              stroke="var(--color-rule)"
            />
            <Tooltip
              cursor={{ fill: "rgba(0,0,0,0.04)" }}
              formatter={(v: any) => [`${v}%`, "score"]}
              contentStyle={{
                fontSize: 12,
                borderRadius: 6,
                border: "1px solid var(--color-rule)",
              }}
            />
            <Bar dataKey="score" radius={[2, 6, 6, 2]}>
              {chartData.map((d) => (
                <Cell
                  key={d.category}
                  fill={
                    d.isPrimary
                      ? "var(--color-felt)"
                      : confColor(d.score / 100)
                  }
                  opacity={d.isPrimary ? 1 : 0.55}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {result.classification.rationale && (
        <div className="flex flex-col gap-1">
          <div className="eyebrow">Model rationale</div>
          <p className="text-[13px] leading-relaxed">
            {result.classification.rationale}
          </p>
        </div>
      )}

      {ocrText && (
        <details className="rounded-lg border p-3" style={{ borderColor: "var(--color-rule)" }}>
          <summary className="cursor-pointer text-[12px] eyebrow">
            OCR transcript ({ocrText.length} chars)
          </summary>
          <pre className="mt-2 text-[11px] font-mono whitespace-pre-wrap max-h-48 overflow-auto opacity-85">
            {ocrText.slice(0, 1200)}
            {ocrText.length > 1200 ? "\n..." : ""}
          </pre>
        </details>
      )}
    </div>
  );
}

function ResultSkeleton() {
  return (
    <div className="flex flex-col gap-3 animate-pulse">
      <div className="flex gap-3">
        <div className="h-12 w-32 rounded bg-black/5" />
        <div className="h-12 w-24 rounded bg-black/5 ml-auto" />
      </div>
      <div className="h-[260px] rounded-lg bg-black/5" />
      <div className="h-3 w-3/4 rounded bg-black/5" />
      <div className="h-3 w-2/3 rounded bg-black/5" />
    </div>
  );
}
