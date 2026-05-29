"use client";

import { useEffect, useMemo, useState } from "react";
import { Search, Filter } from "@/components/icons";

const CATS = [
  "receipt",
  "code_snippet",
  "error_stacktrace",
  "chat_screenshot",
  "meme",
  "document",
  "ui_mockup",
  "chart",
  "other",
];

export default function HistoryPage() {
  const [items, setItems] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<string>("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    const u = new URL("/api/history", window.location.origin);
    if (q) u.searchParams.set("q", q);
    if (cat) u.searchParams.set("category", cat);
    u.searchParams.set("limit", "100");
    fetch(u.toString(), { signal: ctrl.signal })
      .then((r) => r.json())
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [q, cat]);

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const it of items) m[it.primary_category] = (m[it.primary_category] ?? 0) + 1;
    return m;
  }, [items]);

  return (
    <div className="flex flex-col gap-4">
      <header className="glass p-3 flex flex-col md:flex-row gap-3 md:items-center">
        <div className="flex items-center gap-2 flex-1">
          <Search className="w-4 h-4 opacity-60" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="search OCR text or filename"
            className="bg-transparent outline-none w-full text-sm"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 opacity-60" />
          <select
            value={cat}
            onChange={(e) => setCat(e.target.value)}
            className="bg-transparent text-sm border border-white/10 rounded-md px-2 py-1"
          >
            <option value="">all</option>
            {CATS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      </header>

      <div className="flex flex-wrap gap-2 text-xs opacity-80">
        {CATS.map((c) => (
          <span key={c} className="cat-badge">
            {c}: {counts[c] ?? 0}
          </span>
        ))}
      </div>

      {loading && <div className="opacity-60 text-sm">loading…</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((it) => (
          <a
            key={it.id}
            href={`/review/${it.id}`}
            className="glass p-3 flex flex-col gap-2 hover:opacity-90"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="cat-badge">{it.primary_category}</span>
              <span className="text-xs opacity-60">{(it.confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="text-xs opacity-70 truncate">{it.filename}</div>
            <pre className="text-[10px] opacity-70 line-clamp-4 whitespace-pre-wrap">
              {(it.ocr_text || "").slice(0, 200)}
            </pre>
            <div className="text-[10px] opacity-50">
              {new Date(it.created_at).toLocaleString()}
            </div>
          </a>
        ))}
        {!loading && !items.length && (
          <div className="opacity-60 text-sm col-span-full">no matches.</div>
        )}
      </div>
    </div>
  );
}
