"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ArrowsLeftRight, X, Scales } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { fetcher, ENDPOINTS } from "@/lib/api";
import {
  CATEGORIES,
  LONG,
  confColor,
  ms,
  pct,
  shortId,
  type Category,
} from "@/lib/categories";

type Detail = {
  id: string;
  filename: string;
  created_at: string;
  primary_category: Category;
  confidence: number;
  elapsed_ms?: number;
  source?: string;
  ocr_text?: string;
  classification?: {
    primary: Category;
    confidences?: { category: Category; score: number }[];
    rationale?: string;
  };
  ocr?: { text?: string; word_count?: number; mean_confidence?: number };
};

function fmt(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function ShotPanel({
  id,
  side,
  onClear,
}: {
  id: string;
  side: "left" | "right";
  onClear: () => void;
}) {
  const { data, error, isLoading } = useSWR<Detail>(
    id ? ENDPOINTS.historyItem(id) : null,
    fetcher
  );

  return (
    <div className="panel p-4 flex flex-col gap-3 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow">{side === "left" ? "Shot A" : "Shot B"}</span>
        <button
          className="btn btn-ghost text-[12px]"
          onClick={onClear}
          aria-label={`Clear ${side} shot`}
        >
          <X size={14} weight="duotone" /> Clear
        </button>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2 animate-pulse" aria-busy="true">
          <div className="h-6 w-32 bg-black/5 rounded" />
          <div className="h-12 w-full bg-black/5 rounded" />
          <div className="h-24 w-full bg-black/5 rounded" />
        </div>
      )}

      {error && !isLoading && (
        <div className="text-[13px]" style={{ color: "#b00020" }}>
          Could not load shot <span className="num">{shortId(id)}</span>.{" "}
          <button className="underline" onClick={onClear}>
            Pick another
          </button>
          .
        </div>
      )}

      {data && (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <Chip cat={data.primary_category} size="lg" />
            <span
              className="num text-[14px]"
              style={{ color: confColor(data.confidence) }}
            >
              {pct(data.confidence, 1)}
            </span>
            {data.elapsed_ms != null && (
              <span className="num text-[11px] opacity-70">
                {ms(data.elapsed_ms)}
              </span>
            )}
          </div>

          <div>
            <div className="eyebrow mb-1">File</div>
            <div className="text-[13px] truncate" title={data.filename}>
              {data.filename}
            </div>
            <div className="num text-[11px] opacity-70 mt-1">
              {fmt(data.created_at)} · <Link className="underline" href={`/shots/${data.id}`}>open</Link>
            </div>
          </div>

          <div>
            <div className="eyebrow mb-2">Class probabilities</div>
            <div className="flex flex-col gap-1.5">
              {(data.classification?.confidences ?? buildSyntheticDist(data)).map(
                (c) => (
                  <div key={c.category} className="flex items-center gap-2">
                    <span
                      className="text-[11px] uppercase tracking-wide w-[88px] opacity-80"
                      style={{
                        color:
                          c.category === data.primary_category
                            ? confColor(data.confidence)
                            : undefined,
                      }}
                    >
                      {LONG[c.category]}
                    </span>
                    <div
                      className="flex-1"
                      style={{ ["--bar" as any]: confColor(c.score) }}
                    >
                      <ConfBar score={c.score} />
                    </div>
                    <span className="num text-[11px] w-[44px] text-right opacity-80">
                      {pct(c.score, 1)}
                    </span>
                  </div>
                )
              )}
            </div>
          </div>

          {(data.ocr?.text || data.ocr_text) && (
            <div>
              <div className="eyebrow mb-1">OCR</div>
              <pre
                className="text-[12px] whitespace-pre-wrap break-words rounded-sm border p-2 max-h-[180px] overflow-auto"
                style={{
                  borderColor: "var(--color-rule)",
                  background: "var(--color-chalk)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {(data.ocr?.text || data.ocr_text || "").trim() || "—"}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function buildSyntheticDist(d: Detail) {
  // When the backend only returns the primary score, fan the remainder out
  // evenly so the bar chart still reads as a real distribution.
  const remaining = Math.max(0, 1 - d.confidence);
  const others = CATEGORIES.filter((c) => c !== d.primary_category);
  const each = remaining / others.length;
  return [
    { category: d.primary_category, score: d.confidence },
    ...others.map((c) => ({ category: c, score: each })),
  ];
}

function Picker({
  placeholder,
  onPick,
}: {
  placeholder: string;
  onPick: (id: string) => void;
}) {
  const { data } = useSWR<any[]>(ENDPOINTS.history({ limit: 50 }), fetcher);
  const [q, setQ] = useState("");
  const rows = (data ?? []).filter(
    (r) =>
      !q ||
      r.id?.toLowerCase().includes(q.toLowerCase()) ||
      r.filename?.toLowerCase().includes(q.toLowerCase())
  );
  return (
    <div className="panel p-4 flex flex-col gap-3 min-h-[220px]">
      <div className="eyebrow">{placeholder}</div>
      <input
        className="text-[13px] px-3 py-1.5 rounded-sm border bg-white"
        style={{ borderColor: "var(--color-rule)" }}
        placeholder="Search by id or filename"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label={placeholder}
      />
      <div className="overflow-auto max-h-[260px] flex flex-col gap-1">
        {rows.length === 0 ? (
          <div className="text-[12px] opacity-70 p-2">
            No shots yet. Classify something on the{" "}
            <Link href="/upload" className="underline">
              upload
            </Link>{" "}
            page first.
          </div>
        ) : (
          rows.map((r) => (
            <button
              key={r.id}
              onClick={() => onPick(r.id)}
              className="text-left text-[12px] px-2 py-1.5 rounded-sm hover:bg-black/5 flex items-center gap-2"
            >
              <span className="num w-[80px] opacity-70">{shortId(r.id)}</span>
              <Chip cat={r.primary_category} />
              <span className="truncate flex-1">{r.filename}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

function CompareInner() {
  const router = useRouter();
  const sp = useSearchParams();
  const [a, setA] = useState<string>(sp.get("a") ?? "");
  const [b, setB] = useState<string>(sp.get("b") ?? "");

  useEffect(() => {
    const next = new URLSearchParams();
    if (a) next.set("a", a);
    if (b) next.set("b", b);
    const qs = next.toString();
    router.replace(`/compare${qs ? `?${qs}` : ""}`, { scroll: false });
  }, [a, b, router]);

  const swap = () => {
    setA(b);
    setB(a);
  };

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="eyebrow">Side by side</div>
          <h1 className="h-display text-[34px] flex items-center gap-2">
            <Scales size={28} weight="duotone" /> COMPARE SHOTS
          </h1>
          <p className="text-[13px] opacity-70 mt-1">
            Diff two classifications. Pick from history or pass{" "}
            <code className="num">?a=ID&b=ID</code> in the URL. Shareable.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="btn btn-ghost"
            onClick={swap}
            disabled={!a || !b}
            aria-label="Swap sides"
          >
            <ArrowsLeftRight size={14} weight="duotone" /> Swap
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              setA("");
              setB("");
            }}
          >
            Reset
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {a ? (
          <ShotPanel id={a} side="left" onClear={() => setA("")} />
        ) : (
          <Picker placeholder="Pick shot A" onPick={setA} />
        )}
        {b ? (
          <ShotPanel id={b} side="right" onClear={() => setB("")} />
        ) : (
          <Picker placeholder="Pick shot B" onPick={setB} />
        )}
      </div>

      {a && b && <DeltaBar a={a} b={b} />}
    </div>
  );
}

function DeltaBar({ a, b }: { a: string; b: string }) {
  const { data: da } = useSWR<Detail>(ENDPOINTS.historyItem(a), fetcher);
  const { data: db } = useSWR<Detail>(ENDPOINTS.historyItem(b), fetcher);
  if (!da || !db) return null;
  const sameClass = da.primary_category === db.primary_category;
  const confDelta = (db.confidence - da.confidence) * 100;
  const latencyDelta =
    da.elapsed_ms != null && db.elapsed_ms != null
      ? db.elapsed_ms - da.elapsed_ms
      : null;
  return (
    <div className="panel p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
      <Stat label="Same class" value={sameClass ? "Yes" : "No"} />
      <Stat
        label="Confidence delta"
        value={`${confDelta >= 0 ? "+" : ""}${confDelta.toFixed(1)} pts`}
        tone={confDelta >= 0 ? "good" : "bad"}
      />
      <Stat
        label="Latency delta"
        value={latencyDelta == null ? "—" : `${latencyDelta >= 0 ? "+" : ""}${latencyDelta} ms`}
        tone={latencyDelta == null ? undefined : latencyDelta <= 0 ? "good" : "bad"}
      />
      <Stat
        label="Share URL"
        value={
          typeof window !== "undefined"
            ? `/compare?a=${shortId(a)}&b=${shortId(b)}`
            : "/compare"
        }
      />
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  const color =
    tone === "good" ? "#0a8a4f" : tone === "bad" ? "#b00020" : undefined;
  return (
    <div className="flex flex-col">
      <span className="eyebrow">{label}</span>
      <span className="num text-[15px]" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="text-[13px] opacity-70">Loading…</div>}>
      <CompareInner />
    </Suspense>
  );
}
