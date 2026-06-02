"use client";

import { useEffect, useRef, useState } from "react";
import { DownloadSimple, CaretDown, FileCsv, BracketsCurly, ListBullets, Spinner } from "@phosphor-icons/react";
import { ENDPOINTS } from "@/lib/api";

type Format = "csv" | "json" | "ndjson";

type Props = {
  category?: string;
  q?: string;
  limit?: number;
  since?: string;
  until?: string;
  min_conf?: number;
  max_conf?: number;
  sort?: "new" | "old" | "conf_asc" | "conf_desc";
  tag?: string;
  pinned?: boolean;
  disabled?: boolean;
};

export function ExportMenu({
  category,
  q,
  limit = 1000,
  since,
  until,
  min_conf,
  max_conf,
  sort,
  tag,
  pinned,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  async function run(format: Format) {
    setError(null);
    setBusy(format);
    try {
      const url = ENDPOINTS.historyExport({
        format,
        category,
        q,
        limit,
        since,
        until,
        min_conf,
        max_conf,
        sort,
        tag,
        pinned,
      });
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const cd = res.headers.get("content-disposition") || "";
      const match = cd.match(/filename="?([^";]+)"?/i);
      const filename =
        match?.[1] ||
        `shotclassify-history-${new Date()
          .toISOString()
          .replace(/[:.]/g, "-")}.${format}`;
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
      setOpen(false);
    } catch (e: any) {
      setError(e?.message || "Export failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        className="btn btn-ghost flex items-center gap-1.5"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled || !!busy}
        onClick={() => setOpen((v) => !v)}
      >
        {busy ? (
          <Spinner weight="duotone" size={14} className="animate-spin" />
        ) : (
          <DownloadSimple weight="duotone" size={14} />
        )}
        <span>Export</span>
        <CaretDown weight="duotone" size={12} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-1 z-20 min-w-[200px] panel p-1 shadow-lg bg-white"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <button
            role="menuitem"
            className="w-full text-left px-3 py-2 text-[13px] hover:bg-black/5 rounded-sm flex items-center gap-2 disabled:opacity-50"
            disabled={!!busy}
            onClick={() => run("csv")}
          >
            <FileCsv weight="duotone" size={16} />
            <span>CSV (spreadsheet)</span>
          </button>
          <button
            role="menuitem"
            className="w-full text-left px-3 py-2 text-[13px] hover:bg-black/5 rounded-sm flex items-center gap-2 disabled:opacity-50"
            disabled={!!busy}
            onClick={() => run("json")}
          >
            <BracketsCurly weight="duotone" size={16} />
            <span>JSON (full records)</span>
          </button>
          <button
            role="menuitem"
            className="w-full text-left px-3 py-2 text-[13px] hover:bg-black/5 rounded-sm flex items-center gap-2 disabled:opacity-50"
            disabled={!!busy}
            onClick={() => run("ndjson")}
          >
            <ListBullets weight="duotone" size={16} />
            <span>NDJSON (one record per line)</span>
          </button>
          <div className="px-3 py-2 text-[11px] opacity-60 num">
            Up to {limit.toLocaleString()} rows, current filters applied.
          </div>
          {error && (
            <div
              role="alert"
              className="px-3 py-2 text-[11px] text-red-600 border-t"
              style={{ borderColor: "var(--color-rule)" }}
            >
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
