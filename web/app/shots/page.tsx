"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Scales, CaretLeft, CaretRight } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { SampleBadge } from "@/components/SampleBadge";
import { ExportMenu } from "@/components/ExportMenu";
import { fetcherWithMeta, ENDPOINTS } from "@/lib/api";
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
  const [qDebounced, setQDebounced] = useState("");
  const [limit, setLimit] = useState(50);
  const [page, setPage] = useState(0);
  const [since, setSince] = useState(""); // yyyy-mm-dd
  const [until, setUntil] = useState("");
  const [minConfPct, setMinConfPct] = useState(0); // 0..100
  const [sort, setSort] = useState<"new" | "old" | "conf_desc" | "conf_asc">("new");
  const [picked, setPicked] = useState<string[]>([]);

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Reset to first page whenever a filter changes.
  useEffect(() => {
    setPage(0);
  }, [cat, qDebounced, limit, since, until, minConfPct, sort]);

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

  const toIsoStart = (d: string) =>
    d ? new Date(`${d}T00:00:00Z`).toISOString() : undefined;
  const toIsoEnd = (d: string) =>
    d ? new Date(`${d}T23:59:59Z`).toISOString() : undefined;

  const params = useMemo(
    () => ({
      limit,
      offset: page * limit,
      category: cat || undefined,
      q: qDebounced || undefined,
      since: toIsoStart(since),
      until: toIsoEnd(until),
      min_conf: minConfPct > 0 ? minConfPct / 100 : undefined,
      sort,
    }),
    [limit, page, cat, qDebounced, since, until, minConfPct, sort]
  );

  const { data: payload, error, isLoading } = useSWR<{
    data: any;
    total?: number;
    offset?: number;
    limit?: number;
  }>(ENDPOINTS.history(params), fetcherWithMeta, { refreshInterval: 15_000, keepPreviousData: true });

  const data = payload?.data;
  const total = payload?.total ?? 0;

  const isSample = !!error || !Array.isArray(data) || data.length === 0;
  const sampleRows = (makeSampleShots(Math.min(limit, 60)) as unknown as Row[]).filter(
    (r) => (cat ? r.primary_category === cat : true)
  );
  const rows: Row[] = isSample && page === 0 ? sampleRows : (Array.isArray(data) ? (data as Row[]) : []);
  const effectiveTotal = isSample && page === 0 ? sampleRows.length : total;
  const pageCount = Math.max(1, Math.ceil(effectiveTotal / limit));
  const showingFrom = effectiveTotal === 0 ? 0 : page * limit + 1;
  const showingTo = Math.min((page + 1) * limit, effectiveTotal || rows.length);

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
          <span className="num text-[12px] opacity-70">
            {effectiveTotal > 0
              ? `${showingFrom}–${showingTo} of ${effectiveTotal}`
              : `${rows.length} rows`}
          </span>
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
          aria-label="Page size"
        >
          {[25, 50, 100, 200].map((n) => (
            <option key={n} value={n}>
              {n} / page
            </option>
          ))}
        </select>

        <select
          className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white"
          style={{ borderColor: "var(--color-rule)" }}
          value={sort}
          onChange={(e) => setSort(e.target.value as any)}
          aria-label="Sort"
        >
          <option value="new">Newest first</option>
          <option value="old">Oldest first</option>
          <option value="conf_desc">Confidence high to low</option>
          <option value="conf_asc">Confidence low to high</option>
        </select>

        <label className="flex items-center gap-1.5 text-[12px] opacity-80">
          <span className="eyebrow">From</span>
          <input
            type="date"
            className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white"
            style={{ borderColor: "var(--color-rule)" }}
            value={since}
            onChange={(e) => setSince(e.target.value)}
            aria-label="Filter from date"
          />
        </label>

        <label className="flex items-center gap-1.5 text-[12px] opacity-80">
          <span className="eyebrow">To</span>
          <input
            type="date"
            className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white"
            style={{ borderColor: "var(--color-rule)" }}
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            aria-label="Filter to date"
          />
        </label>

        <label className="flex items-center gap-2 text-[12px] opacity-80">
          <span className="eyebrow">Min conf</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={minConfPct}
            onChange={(e) => setMinConfPct(Number(e.target.value))}
            aria-label="Minimum confidence"
          />
          <span className="num text-[11px] w-[34px] text-right">{minConfPct}%</span>
        </label>

        <button
          className="btn btn-ghost"
          onClick={() => {
            setCat("");
            setQ("");
            setLimit(50);
            setSince("");
            setUntil("");
            setMinConfPct(0);
            setSort("new");
            setPage(0);
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
          <div className="p-3 flex flex-col gap-2" aria-label="Loading shots">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-8 rounded-sm animate-pulse"
                style={{ background: "var(--color-rule)", opacity: 0.35 }}
              />
            ))}
          </div>
        ) : error && !rows.length ? (
          <div className="p-8 text-center">
            <div className="eyebrow mb-2" style={{ color: "#b91c1c" }}>
              Couldn't reach the service
            </div>
            <p className="text-sm opacity-70">
              {String((error as Error)?.message || "Network error")}. The table
              will retry automatically.
            </p>
          </div>
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

      <nav
        className="flex items-center justify-between text-[12px] gap-3"
        aria-label="Pagination"
      >
        <span className="opacity-70">
          Page <span className="num">{page + 1}</span> of{" "}
          <span className="num">{pageCount}</span>
          {isSample && " (preview data)"}
        </span>
        <div className="flex items-center gap-2">
          <button
            className="btn btn-ghost"
            onClick={() => setPage(0)}
            disabled={page === 0}
            aria-label="First page"
          >
            First
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            aria-label="Previous page"
          >
            <CaretLeft size={14} weight="duotone" /> Prev
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={page + 1 >= pageCount}
            aria-label="Next page"
          >
            Next <CaretRight size={14} weight="duotone" />
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => setPage(pageCount - 1)}
            disabled={page + 1 >= pageCount}
            aria-label="Last page"
          >
            Last
          </button>
        </div>
      </nav>
    </div>
  );
}
