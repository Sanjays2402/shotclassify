"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CaretDown, CaretUp, FileImage, Lightning, Trash, Warning } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { confColor, LONG, ms, pct, SHORT, type Category } from "@/lib/categories";

type Confidence = { category: Category; score: number };
type Result = {
  id: string;
  filename: string;
  classification: {
    primary: Category;
    confidences: Confidence[];
    rationale?: string;
  };
  ocr?: { text?: string; word_count?: number; mean_confidence?: number };
  elapsed_ms?: number;
};

type Card = {
  key: string;
  filename: string;
  previewUrl: string;
  status: "pending" | "done" | "error";
  result?: Result;
  error?: string;
  startedAt: number;
  finishedAt?: number;
  expanded: boolean;
};

export default function UploadPage() {
  const [cards, setCards] = useState<Card[]>([]);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = cards.some((c) => c.status === "pending");

  // Revoke object URLs on unmount.
  useEffect(() => {
    return () => {
      cards.forEach((c) => URL.revokeObjectURL(c.previewUrl));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFiles = useCallback(async (files: File[]) => {
    const imgs = files.filter((f) => f.type.startsWith("image/"));
    if (!imgs.length) return;

    const fresh: Card[] = imgs.map((f) => ({
      key: `${f.name}-${f.size}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      filename: f.name,
      previewUrl: URL.createObjectURL(f),
      status: "pending",
      startedAt: performance.now(),
      expanded: imgs.length === 1,
    }));
    setCards((prev) => [...fresh, ...prev]);

    for (let i = 0; i < imgs.length; i++) {
      const card = fresh[i];
      try {
        const fd = new FormData();
        fd.append("file", imgs[i]);
        const res = await fetch("/api/classify", { method: "POST", body: fd });
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || `${res.status} ${res.statusText}`);
        }
        const data = (await res.json()) as Result;
        setCards((prev) =>
          prev.map((c) =>
            c.key === card.key
              ? { ...c, status: "done", result: data, finishedAt: performance.now() }
              : c
          )
        );
      } catch (e: any) {
        setCards((prev) =>
          prev.map((c) =>
            c.key === card.key
              ? {
                  ...c,
                  status: "error",
                  error: e?.message ?? "Upload failed.",
                  finishedAt: performance.now(),
                }
              : c
          )
        );
      }
    }
  }, []);

  const removeCard = (key: string) => {
    setCards((prev) => {
      const target = prev.find((c) => c.key === key);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((c) => c.key !== key);
    });
  };

  const toggle = (key: string) =>
    setCards((prev) => prev.map((c) => (c.key === key ? { ...c, expanded: !c.expanded } : c)));

  const clearAll = () => {
    cards.forEach((c) => URL.revokeObjectURL(c.previewUrl));
    setCards([]);
  };

  return (
    <div className="flex flex-col gap-6">
      <header>
        <div className="eyebrow">Ingest</div>
        <h1 className="h-display text-[34px]">UPLOAD A FRAME</h1>
        <p className="text-[13px] opacity-70 mt-1 max-w-[60ch]">
          Drop a screenshot, get a call. PNG, JPEG, WEBP. Multiple files run in parallel.
          Each card shows the image, the primary call, per-class confidence bars, model
          rationale, OCR transcript, and round-trip latency. All from the real pipeline.
        </p>
      </header>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          onFiles(Array.from(e.dataTransfer.files));
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        className="felt p-10 text-center cursor-pointer"
        style={{
          outline: drag ? "2px dashed var(--color-cue)" : "none",
          outlineOffset: -8,
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Drop image files here or press Enter to choose files"
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            onFiles(Array.from(e.target.files ?? []));
            if (inputRef.current) inputRef.current.value = "";
          }}
        />
        <div className="relative z-10">
          <div className="eyebrow mb-3" style={{ color: "var(--color-chalk)" }}>
            {busy ? "On the clock…" : "Drop in"}
          </div>
          <div className="h-display text-[36px] md:text-[48px]">
            {busy ? "CLASSIFYING" : "DRAG. DROP. CALL."}
          </div>
          <p className="opacity-90 mt-3 text-[14px]">
            Or click anywhere to pick files. Press <kbd className="num">U</kbd> to focus.
          </p>
        </div>
      </div>

      {cards.length > 0 && (
        <div className="flex items-center justify-between">
          <div className="eyebrow">
            {cards.length} {cards.length === 1 ? "card" : "cards"}
          </div>
          <button onClick={clearAll} className="btn btn-ghost text-[12px]">
            <Trash size={14} weight="duotone" /> Clear all
          </button>
        </div>
      )}

      {cards.length === 0 ? (
        <div className="panel p-6 text-center text-[13px] opacity-60">
          <FileImage size={28} weight="duotone" className="mx-auto mb-2 opacity-60" />
          No frames yet. Drop one above, or try the{" "}
          <Link href="/demo" className="underline">
            sample gallery
          </Link>
          .
        </div>
      ) : (
        <ul className="flex flex-col gap-3">
          {cards.map((c) => (
            <ResultCard key={c.key} card={c} onToggle={() => toggle(c.key)} onRemove={() => removeCard(c.key)} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ResultCard({
  card,
  onToggle,
  onRemove,
}: {
  card: Card;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const r = card.result;
  const primary = r?.classification?.primary;
  const confs = r?.classification?.confidences ?? [];
  const sorted = [...confs].sort((a, b) => b.score - a.score);
  const primaryScore = sorted[0]?.score ?? 0;
  const latency =
    r?.elapsed_ms ??
    (card.finishedAt != null ? Math.round(card.finishedAt - card.startedAt) : null);

  return (
    <li className="panel p-3">
      <div className="grid grid-cols-[88px_1fr_auto] gap-3 items-start">
        {/* Thumbnail */}
        <div className="w-[88px] h-[88px] bg-[color:var(--color-ink)]/5 overflow-hidden rounded-sm border border-black/10">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={card.previewUrl}
            alt={card.filename}
            className="w-full h-full object-cover"
          />
        </div>

        {/* Header line */}
        <div className="min-w-0 flex flex-col gap-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            {card.status === "pending" && <SkeletonChip />}
            {card.status === "done" && primary && <Chip cat={primary} size="lg" />}
            {card.status === "error" && (
              <span className="num text-[11px] px-2 py-1 border border-[color:var(--color-cat-error)] text-[color:var(--color-cat-error)] rounded-sm flex items-center gap-1">
                <Warning size={12} weight="duotone" /> ERROR
              </span>
            )}
            {card.status === "done" && (
              <span
                className="num text-[18px]"
                style={{ color: confColor(primaryScore) }}
              >
                {pct(primaryScore, 1)}
              </span>
            )}
            {latency != null && (
              <span className="num text-[11px] opacity-60 flex items-center gap-1">
                <Lightning size={12} weight="duotone" /> {ms(latency)}
              </span>
            )}
          </div>
          <div className="text-[13px] truncate" title={card.filename}>
            {r?.id ? (
              <Link
                href={`/shots/${r.id}`}
                className="hover:text-[color:var(--color-felt)]"
              >
                {card.filename}
              </Link>
            ) : (
              card.filename
            )}
          </div>
          {card.status === "error" && (
            <div
              className="text-[12px]"
              style={{ color: "var(--color-cat-error)" }}
            >
              {card.error}
            </div>
          )}
          {card.status === "pending" && (
            <div className="h-1 bg-black/5 rounded overflow-hidden">
              <div className="h-full bg-[color:var(--color-cue)] animate-pulse w-2/3" />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1">
          {card.status === "done" && (
            <button
              onClick={onToggle}
              className="btn btn-ghost text-[12px]"
              aria-expanded={card.expanded}
              aria-label={card.expanded ? "Collapse details" : "Expand details"}
            >
              {card.expanded ? (
                <CaretUp size={14} weight="duotone" />
              ) : (
                <CaretDown size={14} weight="duotone" />
              )}
            </button>
          )}
          <button
            onClick={onRemove}
            className="btn btn-ghost text-[12px]"
            aria-label="Remove card"
          >
            <Trash size={14} weight="duotone" />
          </button>
        </div>
      </div>

      {/* Expanded body */}
      {card.status === "done" && card.expanded && r && (
        <div className="grid md:grid-cols-[1.3fr_1fr] gap-4 mt-4 pt-4 border-t border-black/10">
          <div>
            <div className="eyebrow mb-2">Confidence distribution</div>
            <ul className="flex flex-col gap-1.5">
              {sorted.map((d) => (
                <li
                  key={d.category}
                  className="grid grid-cols-[100px_1fr_56px] items-center gap-3"
                >
                  <span className="text-[11px] num truncate" title={LONG[d.category]}>
                    {SHORT[d.category]}
                  </span>
                  <div
                    style={{
                      ["--bar" as any]: `var(--color-cat-${d.category.split("_")[0]})`,
                    }}
                  >
                    <ConfBar score={d.score} />
                  </div>
                  <span className="num text-[11px] text-right">{pct(d.score, 2)}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-col gap-3">
            {r.classification?.rationale && (
              <div>
                <div className="eyebrow mb-1">Rationale</div>
                <p className="text-[12px] opacity-90 leading-relaxed">
                  {r.classification.rationale}
                </p>
              </div>
            )}
            {r.ocr?.text && (
              <div>
                <div className="eyebrow mb-1">
                  OCR{" "}
                  {r.ocr.word_count != null && (
                    <span className="opacity-60 num">· {r.ocr.word_count} words</span>
                  )}
                </div>
                <pre className="text-[11px] whitespace-pre-wrap leading-snug max-h-[140px] overflow-auto bg-black/[0.03] p-2 rounded-sm border border-black/5">
{r.ocr.text}
                </pre>
              </div>
            )}
            {r.id && (
              <Link href={`/shots/${r.id}`} className="btn btn-ghost text-[12px] self-start">
                Open full replay →
              </Link>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function SkeletonChip() {
  return (
    <span className="inline-block h-[24px] w-[80px] bg-black/10 animate-pulse rounded-sm" />
  );
}
