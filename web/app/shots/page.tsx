"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Scales, CaretLeft, CaretRight, Trash, Tag, CheckSquare, Square, Star, Crosshair } from "@phosphor-icons/react/dist/ssr";
import { useSWRConfig } from "swr";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { ConfBadge } from "@/components/ConfBadge";
import { SampleBadge } from "@/components/SampleBadge";
import { ExportMenu } from "@/components/ExportMenu";
import { EmptyState } from "@/components/EmptyState";
import { SavedViewsBar, type SavedViewFilters } from "@/components/SavedViewsBar";
import { fetcherWithMeta, ENDPOINTS } from "@/lib/api";
import { emptyCopyForList } from "@/lib/empty-state";
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
  label?: string | null;
  tags?: string[];
  pinned?: boolean;
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
  const [tag, setTag] = useState("");
  const [tagDebounced, setTagDebounced] = useState("");
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [bulk, setBulk] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkFlash, setBulkFlash] = useState<
    | { kind: "ok" | "err"; msg: string }
    | null
  >(null);
  const [tagInput, setTagInput] = useState("");
  const { mutate: globalMutate } = useSWRConfig();

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const t = setTimeout(
      () => setTagDebounced(tag.trim().toLowerCase().slice(0, 32)),
      250
    );
    return () => clearTimeout(t);
  }, [tag]);

  // Reset to first page whenever a filter changes.
  useEffect(() => {
    setPage(0);
  }, [cat, qDebounced, limit, since, until, minConfPct, sort, tagDebounced, pinnedOnly]);

  const toggleBulk = (id: string) => {
    setBulk((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
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
      tag: tagDebounced || undefined,
      pinned: pinnedOnly ? true : undefined,
    }),
    [limit, page, cat, qDebounced, since, until, minConfPct, sort, tagDebounced, pinnedOnly]
  );

  const { data: payload, error, isLoading } = useSWR<{
    data: any;
    total?: number;
    offset?: number;
    limit?: number;
  }>(ENDPOINTS.history(params), fetcherWithMeta, { refreshInterval: 15_000, keepPreviousData: true });

  const data = payload?.data;
  const reloadHistory = () =>
    globalMutate(
      (key) => typeof key === "string" && key.startsWith("/api/history"),
      undefined,
      { revalidate: true },
    );
  const onBulkSelectAll = (ids: string[], select: boolean) => {
    setBulk((prev) => {
      const next = new Set(prev);
      if (select) ids.forEach((i) => next.add(i));
      else ids.forEach((i) => next.delete(i));
      return next;
    });
  };
  async function runBulk(
    action: "delete" | "tag_add" | "tag_remove" | "pin" | "unpin",
    tagsArg?: string[],
  ) {
    if (bulkBusy || bulk.size === 0) return;
    setBulkBusy(true);
    setBulkFlash(null);
    try {
      const body: Record<string, unknown> = {
        ids: Array.from(bulk),
        action,
      };
      if (action === "tag_add" || action === "tag_remove") body.tags = tagsArg ?? [];
      const res = await fetch("/api/history/bulk", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const txt = await res.text();
      if (!res.ok) throw new Error(txt || `${res.status}`);
      const json = JSON.parse(txt) as {
        affected: number;
        missing: string[];
      };
      const verb =
        action === "delete"
          ? "deleted"
          : action === "tag_add"
          ? "tagged"
          : action === "tag_remove"
          ? "untagged"
          : action === "pin"
          ? "pinned"
          : "unpinned";
      setBulkFlash({
        kind: "ok",
        msg: `${verb} ${json.affected} shot${json.affected === 1 ? "" : "s"}${
          json.missing?.length ? `, ${json.missing.length} skipped` : ""
        }.`,
      });
      if (action === "delete") setBulk(new Set());
      setTagInput("");
      await reloadHistory();
    } catch (e) {
      setBulkFlash({
        kind: "err",
        msg: (e as Error).message || "Bulk action failed.",
      });
    } finally {
      setBulkBusy(false);
    }
  }
  async function togglePin(row: Row) {
    const want = !row.pinned;
    try {
      const res = await fetch(`/api/shots/${encodeURIComponent(row.id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ pinned: want }),
      });
      if (!res.ok) throw new Error(await res.text());
      await reloadHistory();
    } catch (e) {
      setBulkFlash({
        kind: "err",
        msg: (e as Error).message || "Pin failed.",
      });
    }
  }

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
          <span className="eyebrow">Tag</span>
          <input
            type="text"
            className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white w-[140px]"
            style={{ borderColor: "var(--color-rule)" }}
            value={tag}
            placeholder="any"
            maxLength={32}
            onChange={(e) => setTag(e.target.value)}
            aria-label="Filter by tag"
          />
        </label>

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
          type="button"
          className="btn btn-ghost text-[12px]"
          aria-pressed={pinnedOnly}
          onClick={() => setPinnedOnly((v) => !v)}
          title={pinnedOnly ? "Show every shot" : "Show only pinned shots"}
          style={pinnedOnly ? { color: "#b45309" } : undefined}
        >
          <Star size={14} weight={pinnedOnly ? "fill" : "duotone"} /> Pinned
          {pinnedOnly ? " only" : ""}
        </button>

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
            setTag("");
            setPinnedOnly(false);
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
            since={toIsoStart(since)}
            until={toIsoEnd(until)}
            min_conf={minConfPct > 0 ? minConfPct / 100 : undefined}
            sort={sort}
            tag={tagDebounced || undefined}
            pinned={pinnedOnly ? true : undefined}
            disabled={isSample}
          />
        </div>
      </div>

      <SavedViewsBar
        current={{
          category: cat || undefined,
          q: qDebounced || undefined,
          since: since || undefined,
          until: until || undefined,
          min_conf: minConfPct > 0 ? minConfPct / 100 : undefined,
          sort,
          tag: tagDebounced || undefined,
          limit,
        }}
        onApply={(f: SavedViewFilters) => {
          setCat(((f.category as any) || "") as any);
          setQ(f.q || "");
          setSince(f.since || "");
          setUntil(f.until || "");
          setMinConfPct(
            typeof f.min_conf === "number"
              ? Math.round(f.min_conf * 100)
              : 0,
          );
          setSort((f.sort as any) || "new");
          setTag(f.tag || "");
          if (typeof f.limit === "number") setLimit(f.limit);
          setPage(0);
        }}
      />

      {bulk.size > 0 && (
        <div
          className="panel p-3 flex flex-wrap items-center gap-3"
          role="region"
          aria-label="Bulk actions"
        >
          <span className="eyebrow">
            {bulk.size} selected
          </span>
          <button
            type="button"
            className="btn btn-ghost text-[12px]"
            onClick={() => setBulk(new Set())}
            disabled={bulkBusy}
          >
            Clear
          </button>
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white w-[160px]"
              style={{ borderColor: "var(--color-rule)" }}
              placeholder="tag1, tag2"
              value={tagInput}
              maxLength={96}
              onChange={(e) => setTagInput(e.target.value)}
              aria-label="Tags to add or remove"
              onKeyDown={(e) => {
                if (e.key === "Enter" && tagInput.trim()) {
                  e.preventDefault();
                  const tags = tagInput
                    .split(",")
                    .map((t) => t.trim())
                    .filter(Boolean);
                  if (tags.length) void runBulk("tag_add", tags);
                }
              }}
            />
            <button
              type="button"
              className="btn btn-ghost text-[12px]"
              disabled={bulkBusy || !tagInput.trim()}
              onClick={() => {
                const tags = tagInput
                  .split(",")
                  .map((t) => t.trim())
                  .filter(Boolean);
                if (tags.length) void runBulk("tag_add", tags);
              }}
              title="Add these tags to every selected shot"
            >
              <Tag size={14} weight="duotone" /> Add tag
            </button>
            <button
              type="button"
              className="btn btn-ghost text-[12px]"
              disabled={bulkBusy || !tagInput.trim()}
              onClick={() => {
                const tags = tagInput
                  .split(",")
                  .map((t) => t.trim())
                  .filter(Boolean);
                if (tags.length) void runBulk("tag_remove", tags);
              }}
              title="Remove these tags from every selected shot"
            >
              Remove tag
            </button>
          </div>
          <button
            type="button"
            className="btn btn-ghost text-[12px]"
            disabled={bulkBusy}
            onClick={() => void runBulk("pin")}
            title="Pin every selected shot"
          >
            <Star size={14} weight="fill" /> Pin
          </button>
          <button
            type="button"
            className="btn btn-ghost text-[12px]"
            disabled={bulkBusy}
            onClick={() => void runBulk("unpin")}
            title="Unpin every selected shot"
          >
            <Star size={14} weight="duotone" /> Unpin
          </button>
          <button
            type="button"
            className="btn btn-ghost text-[12px]"
            disabled={bulkBusy}
            onClick={() => {
              if (
                window.confirm(
                  `Delete ${bulk.size} shot${bulk.size === 1 ? "" : "s"}? This cannot be undone.`,
                )
              ) {
                void runBulk("delete");
              }
            }}
            style={{ color: "#b91c1c" }}
          >
            <Trash size={14} weight="duotone" /> Delete
          </button>
          {bulkBusy && (
            <span className="text-[11px] opacity-70" role="status">
              Working...
            </span>
          )}
          {bulkFlash && (
            <span
              role="status"
              className="text-[11px]"
              style={{
                color: bulkFlash.kind === "ok" ? "#15803d" : "#b91c1c",
              }}
            >
              {bulkFlash.msg}
            </span>
          )}
        </div>
      )}

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
          (() => {
            const copy = emptyCopyForList("shots", {
              q: qDebounced,
              category: cat,
              tag: tagDebounced,
              min_conf: minConfPct > 0 ? minConfPct / 100 : 0,
              since,
              until,
              pinnedOnly,
            });
            const filtered =
              !!qDebounced ||
              !!cat ||
              !!tagDebounced ||
              minConfPct > 0 ||
              !!since ||
              !!until ||
              pinnedOnly;
            return (
              <EmptyState
                variant="bare"
                eyebrow={filtered ? "No matches" : "Box score"}
                icon={<Crosshair size={26} weight="duotone" />}
                title={copy.title}
                body={copy.body}
                primary={
                  filtered
                    ? {
                        label: "Reset filters",
                        kind: "cue",
                        onClick: () => {
                          setCat("");
                          setQ("");
                          setLimit(50);
                          setSince("");
                          setUntil("");
                          setMinConfPct(0);
                          setSort("new");
                          setTag("");
                          setPinnedOnly(false);
                          setPage(0);
                          setPicked([]);
                        },
                      }
                    : {
                        label: "Ingest a frame",
                        href: "/upload",
                        kind: "cue",
                      }
                }
                secondary={
                  filtered
                    ? { label: "Ingest a frame", href: "/upload" }
                    : { label: "Try the demo", href: "/demo" }
                }
                data-testid="shots-empty"
              />
            );
          })()
        ) : (
          <div className="overflow-auto max-h-[70vh]">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="w-[28px]" aria-label="Bulk select">
                    {(() => {
                      const ids = rows.map((r) => r.id);
                      const allSelected =
                        ids.length > 0 && ids.every((i) => bulk.has(i));
                      return (
                        <button
                          type="button"
                          aria-label={
                            allSelected
                              ? "Clear page selection"
                              : "Select all rows on this page"
                          }
                          onClick={() => onBulkSelectAll(ids, !allSelected)}
                          className="inline-flex items-center justify-center w-5 h-5"
                          disabled={isSample}
                          title={
                            allSelected ? "Clear page" : "Select page"
                          }
                        >
                          {allSelected ? (
                            <CheckSquare size={16} weight="duotone" />
                          ) : (
                            <Square size={16} weight="duotone" />
                          )}
                        </button>
                      );
                    })()}
                  </th>
                  <th className="w-[28px]" aria-label="Select for compare" />
                  <th className="w-[28px]" aria-label="Pinned" />
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
                        checked={bulk.has(r.id)}
                        onChange={() => toggleBulk(r.id)}
                        disabled={isSample}
                        aria-label={`Select ${shortId(r.id)} for bulk actions`}
                      />
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        checked={picked.includes(r.id)}
                        onChange={() => togglePick(r.id)}
                        aria-label={`Select ${shortId(r.id)} to compare`}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        onClick={() => void togglePin(r)}
                        disabled={isSample}
                        className="inline-flex items-center justify-center w-6 h-6 rounded-sm hover:bg-black/[0.04]"
                        aria-label={r.pinned ? `Unpin ${shortId(r.id)}` : `Pin ${shortId(r.id)}`}
                        aria-pressed={!!r.pinned}
                        title={r.pinned ? "Pinned. Click to unpin." : "Pin this shot"}
                        style={r.pinned ? { color: "#b45309" } : { color: "rgba(0,0,0,0.35)" }}
                      >
                        <Star size={15} weight={r.pinned ? "fill" : "duotone"} />
                      </button>
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
                        <ConfBadge
                          score={r.confidence}
                          size="sm"
                          variant="ghost"
                          digits={1}
                          className="w-[68px] justify-center"
                        />
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
                    <td className="text-[12px] max-w-[260px]">
                      <div className="truncate" title={(r.label && r.label.trim()) || r.filename}>
                        {(r.label && r.label.trim()) || r.filename}
                      </div>
                      {r.tags && r.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {r.tags.slice(0, 4).map((t) => (
                            <button
                              key={t}
                              type="button"
                              onClick={(e) => {
                                e.preventDefault();
                                setTag(t);
                              }}
                              className="num text-[10px] px-1.5 py-[1px] rounded-sm border border-black/15 bg-black/[0.03] hover:bg-black/[0.06]"
                              title={`Filter by tag: ${t}`}
                            >
                              {t}
                            </button>
                          ))}
                          {r.tags.length > 4 && (
                            <span className="num text-[10px] opacity-50">
                              +{r.tags.length - 4}
                            </span>
                          )}
                        </div>
                      )}
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
