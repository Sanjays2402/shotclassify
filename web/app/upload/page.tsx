"use client";

import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { Chip } from "@/components/Chip";
import { confColor, ms, pct } from "@/lib/categories";

type Result = {
  id: string;
  filename: string;
  classification: { primary: any; confidences: { category: any; score: number }[] };
  elapsed_ms?: number;
};

export default function UploadPage() {
  const [results, setResults] = useState<Result[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const onFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    try {
      const out: Result[] = [];
      for (const f of files) {
        const fd = new FormData();
        fd.append("file", f);
        const res = await fetch("/api/classify", { method: "POST", body: fd });
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || `${res.status} ${res.statusText}`);
        }
        out.push(await res.json());
      }
      setResults((r) => [...out, ...r]);
    } catch (e: any) {
      setError(e?.message ?? "Upload failed.");
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <div className="eyebrow">Ingest</div>
        <h1 className="h-display text-[34px]">UPLOAD A FRAME</h1>
        <p className="text-[13px] opacity-70 mt-1 max-w-[60ch]">
          Drop a screenshot, get a call. PNG, JPEG, WEBP. Multiple files run in sequence.
          Confidence and per-class probabilities come back on the same wire.
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
          const files = Array.from(e.dataTransfer.files).filter((f) =>
            f.type.startsWith("image/")
          );
          onFiles(files);
        }}
        className="felt p-10 text-center cursor-pointer"
        style={{
          outline: drag ? "2px dashed var(--color-cue)" : "none",
          outlineOffset: -8,
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
        />
        <div className="relative z-10">
          <div className="eyebrow mb-3" style={{ color: "var(--color-chalk)" }}>
            {busy ? "On the clock…" : "Drop in"}
          </div>
          <div className="h-display text-[36px] md:text-[48px]">
            {busy ? "CLASSIFYING" : "DRAG. DROP. CALL."}
          </div>
          <p className="opacity-90 mt-3 text-[14px]">
            Or click anywhere to pick files.
          </p>
        </div>
      </div>

      {error && (
        <div
          className="panel p-3 text-[13px]"
          style={{ borderColor: "var(--color-cat-error)", color: "var(--color-cat-error)" }}
        >
          {error}
        </div>
      )}

      {results.length > 0 && (
        <section className="flex flex-col gap-3">
          <div className="eyebrow">Most recent calls</div>
          <ul className="flex flex-col gap-2">
            {results.map((r) => {
              const primary = r.classification?.primary;
              const score =
                r.classification?.confidences?.find((c) => c.category === primary)?.score ?? 0;
              return (
                <li
                  key={r.id}
                  className="panel p-3 flex items-center gap-4 flex-wrap"
                >
                  <Chip cat={primary} size="lg" />
                  <Link
                    href={`/shots/${r.id}`}
                    className="text-[14px] hover:text-[color:var(--color-felt)] truncate flex-1 min-w-[140px]"
                  >
                    {r.filename}
                  </Link>
                  <span
                    className="num text-[16px]"
                    style={{ color: confColor(score) }}
                  >
                    {pct(score, 1)}
                  </span>
                  <span className="num text-[12px] opacity-70">
                    {ms(r.elapsed_ms ?? 0)}
                  </span>
                  <Link
                    href={`/shots/${r.id}`}
                    className="btn btn-ghost"
                  >
                    Replay →
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
