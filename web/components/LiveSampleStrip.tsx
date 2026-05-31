"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CursorClick, Lightning, Sparkle, Warning } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { confColor, LONG, ms, pct, type Category } from "@/lib/categories";

type Confidence = { category: Category; score: number };

type Result = {
  id: string;
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
  expected: Category;
  src: string;
};

const SAMPLES: Sample[] = [
  { slug: "receipt", title: "Receipt",     expected: "receipt",          src: "/samples/fake-receipt.png" },
  { slug: "code",    title: "Code snippet", expected: "code_snippet",     src: "/samples/fake-code.png" },
  { slug: "error",   title: "Stack trace",  expected: "error_stacktrace", src: "/samples/fake-error.png" },
  { slug: "chat",    title: "Group chat",   expected: "chat_screenshot",  src: "/samples/fake-chat.png" },
];

export default function LiveSampleStrip() {
  const [active, setActive] = useState<Sample>(SAMPLES[0]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);

  const run = useCallback(async (s: Sample) => {
    const myReq = ++reqId.current;
    setActive(s);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const blob = await fetch(s.src).then((r) => {
        if (!r.ok) throw new Error(`could not load ${s.src}`);
        return r.blob();
      });
      const file = new File([blob], `${s.slug}.png`, { type: blob.type || "image/png" });
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
      if (myReq === reqId.current) setResult(json);
    } catch (e: any) {
      if (myReq === reqId.current) setError(e?.message ?? "Classification failed.");
    } finally {
      if (myReq === reqId.current) setBusy(false);
    }
  }, []);

  // Auto-run first sample once on mount so the panel never sits empty.
  useEffect(() => {
    run(SAMPLES[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sorted = (result?.classification.confidences ?? [])
    .slice()
    .sort((a, b) => b.score - a.score);
  const primary = result?.classification.primary;
  const top = sorted[0];

  return (
    <section
      className="rounded-2xl border overflow-hidden"
      style={{ borderColor: "var(--color-rule)", background: "var(--color-chalk)" }}
    >
      <div
        className="px-4 md:px-5 py-3 border-b flex items-center justify-between gap-3 flex-wrap"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <div className="flex items-center gap-2">
          <Sparkle weight="duotone" size={16} />
          <span className="eyebrow">Try it now</span>
          <span className="text-[12px] opacity-70 hidden sm:inline">
            One click. Real model. No upload.
          </span>
        </div>
        <Link
          href="/demo"
          className="text-[12px] underline opacity-80 hover:opacity-100"
          aria-label="Open the full demo"
        >
          Open full demo
        </Link>
      </div>

      <div className="grid md:grid-cols-[1fr_1.1fr]">
        {/* Sample picker */}
        <div className="p-3 md:p-4 border-b md:border-b-0 md:border-r" style={{ borderColor: "var(--color-rule)" }}>
          <div className="grid grid-cols-2 gap-2">
            {SAMPLES.map((s) => {
              const selected = s.slug === active.slug;
              return (
                <button
                  key={s.slug}
                  onClick={() => run(s)}
                  disabled={busy && selected}
                  aria-pressed={selected}
                  className="group text-left rounded-xl border overflow-hidden focus:outline-none focus:ring-2 transition-shadow disabled:cursor-progress"
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
                    {!selected && (
                      <div className="absolute bottom-1.5 right-1.5 rounded-md px-1.5 py-0.5 bg-white/90 flex items-center gap-1 text-[10px]">
                        <CursorClick weight="duotone" size={12} />
                        Classify
                      </div>
                    )}
                  </div>
                  <div className="p-2 flex items-center justify-between gap-2">
                    <span className="text-[12px] font-medium truncate">{s.title}</span>
                    <Chip cat={s.expected} />
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Live prediction */}
        <div className="p-3 md:p-4 flex flex-col gap-3 min-h-[260px]">
          <div className="flex items-center gap-2">
            <Lightning weight="duotone" size={16} />
            <span className="eyebrow">Prediction</span>
            {result?.elapsed_ms != null && (
              <span className="num text-[11px] opacity-70 ml-auto">{ms(result.elapsed_ms)}</span>
            )}
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

          {busy && !result && !error && <StripSkeleton />}

          {result && !busy && primary && (
            <>
              <div className="flex items-baseline justify-between gap-3 flex-wrap">
                <div>
                  <div className="eyebrow">Primary</div>
                  <div className="h-display text-[22px]">{LONG[primary] ?? primary}</div>
                </div>
                {top && (
                  <div className="text-right">
                    <div className="eyebrow">Confidence</div>
                    <div
                      className="h-display text-[22px]"
                      style={{ color: confColor(top.score) }}
                    >
                      {pct(top.score)}
                    </div>
                  </div>
                )}
              </div>
              <ul className="flex flex-col gap-1.5">
                {sorted.slice(0, 5).map((c) => (
                  <li
                    key={c.category}
                    className="grid grid-cols-[88px_1fr_44px] items-center gap-3"
                  >
                    <Chip cat={c.category} />
                    <ConfBar score={c.score} />
                    <span className="num text-[11px] text-right">{pct(c.score)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {!busy && !result && !error && (
            <div className="text-[13px] opacity-70">
              Pick a sample to see the model predictions.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function StripSkeleton() {
  return (
    <div className="flex flex-col gap-3 animate-pulse">
      <div className="flex justify-between">
        <div className="h-7 w-32 rounded bg-black/10" />
        <div className="h-7 w-16 rounded bg-black/10" />
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="grid grid-cols-[88px_1fr_44px] items-center gap-3">
          <div className="h-5 rounded bg-black/10" />
          <div className="h-3 rounded bg-black/10" />
          <div className="h-3 rounded bg-black/10" />
        </div>
      ))}
    </div>
  );
}
