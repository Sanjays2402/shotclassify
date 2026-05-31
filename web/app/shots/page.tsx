"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Scales } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { SampleBadge } from "@/components/SampleBadge";
import { ExportMenu } from "@/components/ExportMenu";
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
import { makeSampleShots } from "@/lib/sample";

type Row = {
  id: string;
  filename: string;
  primary_category: Category;
  confidence: number;
  elapsed_ms?: number;
  source?: string;
  created_at: string;
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function ShotsPage() {
  const router = useRouter();
  const [cat, setCat] = useState<"" | Category>("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(100);
  const [picked, setPicked] = useState<string[]>([]);

  const togglePick = (id: string) => {
    setPicked((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  };

  const goCompare = () => {
    if (picked.length !== 2) return;
    router.push(`/compare?a=${picked[0]}&b=${picked[1]}`);
  };

  const { data, error, isLoading } = useSWR<any[]>(
    ENDPOINTS.history({
      limit,
      category: cat || undefined,
      q: q || undefined,
    }),
    fetcher,
    { refreshInterval: 10_000 }
  );

  const isSample = error || !Array.isArray(data) || data.length === 0;
  const rows: Row[] = isSample
    ? (makeSampleShots(Math.min(limit, 60)) as unknown as Row[]).filter((r) =>
        cat ? r.primary_category === cat : true
      )
    : (data as Row[]);

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="eyebrow">Box score</div>
          <h1 className="h-display text-[34px]">ALL SHOTS</h1>
          <p className="text-[13px] opacity-70 mt-1">
            Every classification the service has called. Filter by class, search the OCR.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isSample && <SampleBadge />}
          <span className="num text-[12px] opacity-70">{rows.length} rows</span>
        </div>
      </header>

      <div
        className="panel p-3 flex flex-wrap items-center gap-3"
        role="toolbar"
        aria-label="Filters"
      >
        <select
          className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white"
          style={{ borderColor: "var(--color-rule)" }}
          value={cat}
          onChange={(e) => setCat(e.target.value as any)}
          aria-label="Filter by class"
        >
          <option value="">All classes</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {LONG[c]}
            </option>
          ))}
        </select>

        <input
          className="text-[13px] px-3 py-1.5 rounded-sm border bg-white min-w-[260px] flex-1"
          style={{ borderColor: "var(--color-rule)" }}
          placeholder="Search OCR text or filename"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />

        <select
          className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white"
          style={{ borderColor: "var(--color-rule)" }}
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          aria-label="Row limit"
        >
          {[50, 100, 200, 500].map((n) => (
            <option key={n} value={n}>
              {n} rows
            </option>
          ))}
        </select>

        <button
          className="btn btn-ghost"
          onClick={() => {
            setCat("");
            setQ("");
            setLimit(100);
            setPicked([]);
          }}
        >
          Reset
        </button>

        <button
          className="btn btn-ghost"
          onClick={goCompare}
          disabled={picked.length !== 2}
          aria-label="Compare selected shots"
          title={
            picked.length === 2
              ? "Open compare view"
              : "Select two rows to compare"
          }
        >
          <Scales size={14} weight="duotone" /> Compare ({picked.length}/2)
        </button>

        <div className="ml-auto">
          <ExportMenu
            category={cat || undefined}
            q={q || undefined}
            limit={Math.max(limit, 1000)}
            disabled={isSample}
          />
        </div>
      </div>

      <div className="panel overflow-hidden">
        {isLoading && !rows.length ? (
          <div className="p-6 text-sm opacity-70">Pulling the tape…</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center">
            <div className="eyebrow mb-2">No record</div>
            <p className="text-sm opacity-70">
              Nothing under that filter. Try widening the search or{" "}
              <Link href="/upload" className="underline">
                feed the model
              </Link>
              .
            </p>
          </div>
        ) : (
          <div className="overflow-auto max-h-[70vh]">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="w-[28px]" aria-label="Select for compare" />
                  <th>ID</th>
                  <th>Class</th>
                  <th>Confidence</th>
                  <th className="w-[120px]">Latency</th>
                  <th>Source</th>
                  <th>File</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} data-picked={picked.includes(r.id)}>
                    <td>
                      <input
                        type="checkbox"
                        checked={picked.includes(r.id)}
                        onChange={() => togglePick(r.id)}
                        aria-label={`Select ${shortId(r.id)} to compare`}
                      />
                    </td>
                    <td>
                      <Link
                        href={`/shots/${r.id}`}
                        className="num text-[12px] hover:text-[color:var(--color-felt)]"
                      >
                        {shortId(r.id)}
                      </Link>
                    </td>
                    <td>
                      <Chip cat={r.primary_category} />
                    </td>
                    <td>
                      <div className="flex items-center gap-2 min-w-[180px]">
                        <span
                          className="num text-[12px] w-[52px]"
                          style={{ color: confColor(r.confidence) }}
                        >
                          {pct(r.confidence, 1)}
                        </span>
                        <div
                          className="flex-1"
                          style={{ ["--bar" as any]: confColor(r.confidence) }}
                        >
                          <ConfBar score={r.confidence} />
                        </div>
                      </div>
                    </td>
                    <td className="num text-[12px]">
                      {r.elapsed_ms != null ? ms(r.elapsed_ms) : "—"}
                    </td>
                    <td className="num text-[11px] opacity-70">
                      {r.source ?? "api"}
                    </td>
                    <td className="text-[12px] max-w-[260px] truncate">
                      {r.filename}
                    </td>
                    <td className="num text-[11px] opacity-70 whitespace-nowrap">
                      {fmtTime(r.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
