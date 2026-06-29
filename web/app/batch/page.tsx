"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import Link from "next/link";
import JSZip from "jszip";
import {
  Archive,
  CheckCircle,
  DownloadSimple,
  FileImage,
  Spinner,
  Trash,
  Warning,
  XCircle,
} from "@phosphor-icons/react/dist/ssr";
import { ConfBar } from "@/components/ConfBar";
import { confColor, LONG, pct, type Category } from "@/lib/categories";
import {
  progressPercent,
  isBatchComplete,
  progressLabel,
} from "@/lib/batch-progress";

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center text-[11px] px-2 py-0.5 rounded border tabular-nums"
      style={{ borderColor: "var(--color-rule)", color: "var(--color-mute)" }}
    >
      {children}
    </span>
  );
}

type Row = {
  key: string;
  filename: string;
  size: number;
  status: "queued" | "running" | "done" | "error";
  startedAt?: number;
  finishedAt?: number;
  shotId?: string;
  primary?: Category;
  confidence?: number;
  error?: string;
};

const IMAGE_EXTS = ["png", "jpg", "jpeg", "gif", "webp", "bmp"];
const MAX_CONCURRENCY = 3;

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

function isImageName(name: string): boolean {
  if (name.startsWith("__MACOSX/")) return false;
  const base = name.split("/").pop() || "";
  if (base.startsWith(".")) return false;
  return IMAGE_EXTS.includes(extOf(base));
}

function mimeOf(name: string): string {
  const e = extOf(name);
  if (e === "jpg" || e === "jpeg") return "image/jpeg";
  if (e === "png") return "image/png";
  if (e === "gif") return "image/gif";
  if (e === "webp") return "image/webp";
  if (e === "bmp") return "image/bmp";
  return "application/octet-stream";
}

function csvCell(v: unknown): string {
  if (v === undefined || v === null) return "";
  const s = String(v);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export default function BatchPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [drag, setDrag] = useState(false);
  const [running, setRunning] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [stage, setStage] = useState<string>("");
  const filesRef = useRef<Map<string, { name: string; blob: Blob }>>(new Map());
  const zipInputRef = useRef<HTMLInputElement>(null);
  const imgInputRef = useRef<HTMLInputElement>(null);

  const counts = useMemo(() => {
    const total = rows.length;
    const done = rows.filter((r) => r.status === "done").length;
    const err = rows.filter((r) => r.status === "error").length;
    const pending = total - done - err;
    return { total, done, err, pending };
  }, [rows]);

  const reset = useCallback(() => {
    if (running) return;
    setRows([]);
    setGlobalError(null);
    setStage("");
    filesRef.current.clear();
  }, [running]);

  const ingestFiles = useCallback(async (incoming: File[]) => {
    setGlobalError(null);
    setStage("Inspecting input");
    const newEntries: { key: string; name: string; size: number; blob: Blob }[] = [];

    for (const f of incoming) {
      const lower = f.name.toLowerCase();
      const isZip =
        lower.endsWith(".zip") ||
        f.type === "application/zip" ||
        f.type === "application/x-zip-compressed";
      if (isZip) {
        setStage(`Extracting ${f.name}`);
        try {
          const zip = await JSZip.loadAsync(f);
          const names = Object.keys(zip.files).filter((n) => !zip.files[n].dir && isImageName(n));
          if (names.length === 0) {
            setGlobalError(`No images found in ${f.name}.`);
            continue;
          }
          for (const n of names) {
            const blob = await zip.files[n].async("blob");
            const base = n.split("/").pop() || n;
            const typed = blob.type ? blob : new Blob([blob], { type: mimeOf(base) });
            const key = `${base}-${typed.size}-${newEntries.length}-${Math.random().toString(36).slice(2, 6)}`;
            newEntries.push({ key, name: base, size: typed.size, blob: typed });
          }
        } catch (e: any) {
          setGlobalError(`Failed to read ${f.name}: ${e?.message ?? "invalid zip"}`);
        }
      } else if (f.type.startsWith("image/") || IMAGE_EXTS.includes(extOf(f.name))) {
        const key = `${f.name}-${f.size}-${newEntries.length}-${Math.random().toString(36).slice(2, 6)}`;
        newEntries.push({ key, name: f.name, size: f.size, blob: f });
      }
    }

    if (newEntries.length === 0) {
      setStage("");
      if (!globalError) setGlobalError("Drop a .zip of images, or one or more image files.");
      return;
    }

    for (const e of newEntries) filesRef.current.set(e.key, { name: e.name, blob: e.blob });
    setRows((prev) => [
      ...prev,
      ...newEntries.map<Row>((e) => ({
        key: e.key,
        filename: e.name,
        size: e.size,
        status: "queued",
      })),
    ]);
    setStage("");
  }, [globalError]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDrag(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length) ingestFiles(files);
    },
    [ingestFiles],
  );

  const classifyOne = useCallback(
    async (row: Row): Promise<Row> => {
      const f = filesRef.current.get(row.key);
      if (!f) return { ...row, status: "error", error: "missing file" };
      const fd = new FormData();
      fd.append("file", f.blob, f.name);
      try {
        const res = await fetch("/api/classify", { method: "POST", body: fd });
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          return {
            ...row,
            status: "error",
            error: text.slice(0, 200) || `${res.status} ${res.statusText}`,
            finishedAt: performance.now(),
          };
        }
        const json = await res.json();
        const primary: Category = json?.classification?.primary;
        const confs = json?.classification?.confidences ?? [];
        const top = confs.find((c: any) => c.category === primary);
        return {
          ...row,
          status: "done",
          shotId: json?.id,
          primary,
          confidence: top?.score,
          finishedAt: performance.now(),
        };
      } catch (e: any) {
        return {
          ...row,
          status: "error",
          error: e?.message ?? "network error",
          finishedAt: performance.now(),
        };
      }
    },
    [],
  );

  const runAll = useCallback(async () => {
    if (running) return;
    const queue = rows.filter((r) => r.status === "queued" || r.status === "error");
    if (!queue.length) return;
    setRunning(true);
    setGlobalError(null);
    setStage(`Classifying ${queue.length} images`);

    // Mark queued as running visually one-by-one in batches.
    const indexByKey = new Map(rows.map((r, i) => [r.key, i]));
    let cursor = 0;
    const total = queue.length;

    const worker = async () => {
      while (cursor < total) {
        const item = queue[cursor++];
        if (!item) break;
        setRows((prev) => {
          const next = prev.slice();
          const i = indexByKey.get(item.key);
          if (i !== undefined) next[i] = { ...next[i], status: "running", startedAt: performance.now() };
          return next;
        });
        const finished = await classifyOne(item);
        setRows((prev) => {
          const next = prev.slice();
          const i = indexByKey.get(item.key);
          if (i !== undefined) next[i] = finished;
          return next;
        });
      }
    };

    const workers = Array.from({ length: Math.min(MAX_CONCURRENCY, queue.length) }, () => worker());
    await Promise.all(workers);

    setStage("");
    setRunning(false);
  }, [classifyOne, rows, running]);

  const downloadCsv = useCallback(() => {
    const header = ["id", "filename", "size_bytes", "status", "primary", "confidence", "elapsed_ms", "error"];
    const lines = [header.join(",")];
    for (const r of rows) {
      const elapsed = r.startedAt && r.finishedAt ? Math.round(r.finishedAt - r.startedAt) : "";
      lines.push(
        [
          r.shotId ?? "",
          r.filename,
          r.size,
          r.status,
          r.primary ?? "",
          r.confidence !== undefined ? r.confidence.toFixed(4) : "",
          elapsed,
          r.error ?? "",
        ]
          .map(csvCell)
          .join(","),
      );
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `shotclassify-batch-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [rows]);

  const onPickZip = () => zipInputRef.current?.click();
  const onPickImages = () => imgInputRef.current?.click();

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">Batch</p>
          <h1 className="h-display text-[28px] tracking-tight">Bulk classify a zip of images</h1>
          <p className="text-[13px] mt-1" style={{ color: "var(--color-mute)" }}>
            Drop a .zip from your shoot or a folder of stills. Each image runs through the live pipeline and lands in your history. Download a CSV when you are done.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/shots" className="text-[12px] underline-offset-2 hover:underline">
            View history
          </Link>
        </div>
      </header>

      <section
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className="rounded-lg border-2 border-dashed p-8 text-center transition-colors"
        style={{
          borderColor: drag ? "var(--color-felt)" : "var(--color-rule)",
          background: drag ? "color-mix(in oklab, var(--color-felt) 6%, transparent)" : "transparent",
        }}
      >
        <div className="flex justify-center mb-3">
          <Archive size={36} weight="duotone" />
        </div>
        <div className="text-[14px] font-medium">Drop a .zip or images here</div>
        <div className="text-[12px] mt-1" style={{ color: "var(--color-mute)" }}>
          PNG, JPG, WEBP, GIF, BMP. Up to a few hundred per zip works comfortably.
        </div>
        <div className="mt-4 flex justify-center gap-2 flex-wrap">
          <button
            onClick={onPickZip}
            className="text-[12px] px-3 py-1.5 rounded border"
            style={{ borderColor: "var(--color-rule)" }}
          >
            Pick a .zip
          </button>
          <button
            onClick={onPickImages}
            className="text-[12px] px-3 py-1.5 rounded border"
            style={{ borderColor: "var(--color-rule)" }}
          >
            Pick images
          </button>
          <input
            ref={zipInputRef}
            type="file"
            accept=".zip,application/zip,application/x-zip-compressed"
            className="hidden"
            onChange={(e) => {
              const fs = Array.from(e.target.files ?? []);
              if (fs.length) ingestFiles(fs);
              if (zipInputRef.current) zipInputRef.current.value = "";
            }}
          />
          <input
            ref={imgInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => {
              const fs = Array.from(e.target.files ?? []);
              if (fs.length) ingestFiles(fs);
              if (imgInputRef.current) imgInputRef.current.value = "";
            }}
          />
        </div>
        {stage && (
          <div className="text-[11px] mt-3 inline-flex items-center gap-1.5" style={{ color: "var(--color-mute)" }}>
            <Spinner size={12} className="animate-spin" /> {stage}
          </div>
        )}
        {globalError && (
          <div className="text-[12px] mt-3 inline-flex items-center gap-1.5" style={{ color: "#b42318" }}>
            <Warning size={14} weight="duotone" /> {globalError}
          </div>
        )}
      </section>

      {rows.length > 0 && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Pill>{counts.total} files</Pill>
            <Pill>{counts.done} done</Pill>
            {counts.err > 0 && <Pill>{counts.err} errors</Pill>}
            {counts.pending > 0 && <Pill>{counts.pending} pending</Pill>}
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={runAll}
                disabled={running || counts.pending === 0}
                className="text-[12px] px-3 py-1.5 rounded border disabled:opacity-40"
                style={{
                  borderColor: "var(--color-felt)",
                  background: "var(--color-felt)",
                  color: "var(--color-chalk)",
                }}
              >
                {running ? "Running…" : counts.pending === 0 ? "All done" : `Run ${counts.pending}`}
              </button>
              <button
                onClick={downloadCsv}
                disabled={counts.done === 0}
                className="text-[12px] px-3 py-1.5 rounded border disabled:opacity-40 inline-flex items-center gap-1.5"
                style={{ borderColor: "var(--color-rule)" }}
              >
                <DownloadSimple size={14} weight="duotone" /> Download CSV
              </button>
              <button
                onClick={reset}
                disabled={running}
                className="text-[12px] px-3 py-1.5 rounded border disabled:opacity-40 inline-flex items-center gap-1.5"
                style={{ borderColor: "var(--color-rule)" }}
              >
                <Trash size={14} weight="duotone" /> Clear
              </button>
            </div>
          </div>

          {/* Determinate progress bar (this tick) -- the pills tally counts but
              gave no sense of how far along a long run is. Fills felt-green as
              rows settle, flips to a complete treatment at 100%, and names any
              errors in the label below. */}
          {(() => {
            const percent = progressPercent(counts);
            const complete = isBatchComplete(counts);
            const label = progressLabel(counts);
            return (
              <div className="flex flex-col gap-1.5">
                <div
                  className="h-2 w-full rounded-full overflow-hidden"
                  style={{ background: "var(--color-rule)" }}
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={percent}
                  aria-label="Batch classification progress"
                >
                  <div
                    className="h-full rounded-full transition-[width] duration-300 ease-out"
                    style={{
                      width: `${percent}%`,
                      background: complete
                        ? "#067647"
                        : "var(--color-felt)",
                    }}
                  />
                </div>
                <div className="flex items-center justify-between text-[11px] tabular-nums" style={{ color: "var(--color-mute)" }}>
                  <span>{label}</span>
                  <span>{percent}%</span>
                </div>
              </div>
            );
          })()}

          <div
            className="overflow-x-auto rounded border"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left" style={{ background: "var(--color-chalk)" }}>
                  <th className="px-3 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">File</th>
                  <th className="px-3 py-2 font-medium">Size</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Class</th>
                  <th className="px-3 py-2 font-medium w-[160px]">Confidence</th>
                  <th className="px-3 py-2 font-medium">Open</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.key} className="border-t" style={{ borderColor: "var(--color-rule)" }}>
                    <td className="px-3 py-2 tabular-nums" style={{ color: "var(--color-mute)" }}>{i + 1}</td>
                    <td className="px-3 py-2 truncate max-w-[260px]" title={r.filename}>
                      <span className="inline-flex items-center gap-1.5">
                        <FileImage size={14} weight="duotone" />
                        {r.filename}
                      </span>
                    </td>
                    <td className="px-3 py-2 tabular-nums" style={{ color: "var(--color-mute)" }}>
                      {fmtBytes(r.size)}
                    </td>
                    <td className="px-3 py-2">
                      {r.status === "queued" && <span style={{ color: "var(--color-mute)" }}>queued</span>}
                      {r.status === "running" && (
                        <span className="inline-flex items-center gap-1.5">
                          <Spinner size={12} className="animate-spin" /> running
                        </span>
                      )}
                      {r.status === "done" && (
                        <span className="inline-flex items-center gap-1.5" style={{ color: "#067647" }}>
                          <CheckCircle size={14} weight="duotone" /> done
                        </span>
                      )}
                      {r.status === "error" && (
                        <span className="inline-flex items-center gap-1.5" style={{ color: "#b42318" }} title={r.error}>
                          <XCircle size={14} weight="duotone" /> error
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {r.primary ? (
                        <span
                          className="inline-block px-1.5 py-0.5 rounded text-[11px] font-medium"
                          style={{
                            background: `${confColor(r.confidence ?? 0)}22`,
                            color: confColor(r.confidence ?? 0),
                          }}
                        >
                          {LONG[r.primary]}
                        </span>
                      ) : (
                        <span style={{ color: "var(--color-mute)" }}>—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {r.confidence !== undefined ? (
                        <div className="flex items-center gap-2">
                          <ConfBar score={r.confidence} />
                          <span className="tabular-nums">{pct(r.confidence)}</span>
                        </div>
                      ) : (
                        <span style={{ color: "var(--color-mute)" }}>—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {r.shotId ? (
                        <Link
                          href={`/shots/${r.shotId}`}
                          className="underline-offset-2 hover:underline"
                          style={{ color: "var(--color-felt)" }}
                        >
                          open
                        </Link>
                      ) : (
                        <span style={{ color: "var(--color-mute)" }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {rows.length === 0 && !globalError && !stage && (
        <p className="text-[12px]" style={{ color: "var(--color-mute)" }}>
          Tip: a zip exported from Finder, Drive, or Dropbox works out of the box. Hidden files and __MACOSX folders are ignored.
        </p>
      )}
    </div>
  );
}
