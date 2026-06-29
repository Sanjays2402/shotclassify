"use client";

import { useEffect, useMemo, useRef, useState, Suspense, Fragment } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Scales, CaretLeft, CaretRight, CaretDown, Trash, Tag, CheckSquare, Square, Star, Crosshair, Table, GridFour, Rows, Funnel, DotsThreeOutline } from "@phosphor-icons/react/dist/ssr";
import { useSWRConfig } from "swr";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { ConfBadge } from "@/components/ConfBadge";
import { SampleBadge } from "@/components/SampleBadge";
import { ExportMenu } from "@/components/ExportMenu";
import { EmptyState } from "@/components/EmptyState";
import { SkeletonRows } from "@/components/Skeleton";
import { SavedViewsBar, type SavedViewFilters } from "@/components/SavedViewsBar";
import { FilterBreadcrumb } from "@/components/FilterBreadcrumb";
import { ShotGrid } from "@/components/ShotGrid";
import {
  parseGridDensity,
  writeGridDensity,
  labelForGridDensity,
  nextGridDensity,
  GRID_DENSITIES,
  GRID_DENSITY_DEFAULT,
  GRID_DENSITY_STORAGE_KEY,
  type GridDensity,
} from "@/lib/grid-density";
import CopyViewLinkButton from "@/components/CopyViewLinkButton";
import BulkExportButtons from "@/components/BulkExportButtons";
import RowExportMenu from "@/components/RowExportMenu";
import { ShotPreviewRow } from "@/components/ShotPreviewDrawer";
import {
  expandAllPreviews,
  collapseAllPreviews,
  allPreviewsExpanded,
  previewToggleAllLabel,
} from "@/lib/preview-expand";
import { pickPreviewTarget } from "@/lib/preview-key";
import { rangeOfTotalLabel, countLabel } from "@/lib/count-label";
import { shotRowToExportInput, type ShotExportInput } from "@/lib/shot-export";
import { fetcherWithMeta, ENDPOINTS } from "@/lib/api";
import { emptyCopyForList } from "@/lib/empty-state";
import { filterCountLabel, type FilterKey } from "@/lib/filter-summary";
import { confFloorReadout } from "@/lib/conf-floor";
import { filterTabIndex } from "@/lib/filter-order";
import {
  parseViewMode,
  nextViewMode,
  labelForViewMode,
  isTabular,
  isCompact,
  SHOTS_VIEW_STORAGE_KEY,
  SHOTS_VIEW_MODES,
  type ShotsViewMode,
} from "@/lib/view-mode";
import { toast } from "@/lib/toast-store";
import { parseShotsDeepLink, hasDeepLink } from "@/lib/shots-deeplink";
import { shotsDocTitle } from "@/lib/shots-doc-title";
import {
  parseShotsPageSize,
  writeShotsPageSize,
  SHOTS_PAGE_SIZES,
  SHOTS_PAGE_SIZE_STORAGE_KEY,
  type ShotsPageSize,
} from "@/lib/shots-page-size";
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

function ShotsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
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
  const [tagInput, setTagInput] = useState("");
  const [view, setView] = useState<ShotsViewMode>("table");
  const [gridDensity, setGridDensity] = useState<GridDensity>(GRID_DENSITY_DEFAULT);
  // Per-row inline preview drawer (F84): the set of row ids currently expanded
  // under the table. A row's detail is lazily fetched only while it's open.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Latest visible row ids, mutated during render (idempotent) so the bind-once
  // `o` keyboard handler (F118) can read the current page's rows without
  // re-binding the listener on every data change.
  const visibleIdsRef = useRef<string[]>([]);
  const { mutate: globalMutate } = useSWRConfig();

  function toggleExpanded(id: string) {
    setExpanded((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Expand or collapse EVERY visible row's preview at once (F119). Flips based
  // on whether the visible rows are already all-open, and preserves the open
  // state of any rows that aren't on this page (the expanded set spans
  // pagination). The visible ids are passed in from render since `rows` is
  // derived there.
  function toggleAllPreviews(ids: string[]) {
    setExpanded((cur) =>
      allPreviewsExpanded(cur, ids)
        ? collapseAllPreviews(cur, ids)
        : expandAllPreviews(cur, ids),
    );
  }

  // Load the persisted view mode once on mount (SSR can't know it).
  useEffect(() => {
    try {
      setView(parseViewMode(window.localStorage.getItem(SHOTS_VIEW_STORAGE_KEY)));
    } catch {
      // Storage blocked -- stay on the table default.
    }
  }, []);

  // Load the persisted grid density once on mount (F29), mirroring the view
  // load. A return visit to the grid reopens on the column density you last
  // picked. Storage failures leave the default intact.
  useEffect(() => {
    try {
      setGridDensity(
        parseGridDensity(window.localStorage.getItem(GRID_DENSITY_STORAGE_KEY)),
      );
    } catch {
      // Storage blocked -- stay on the default density.
    }
  }, []);

  // Change + persist the grid density together so the next visit reopens here.
  const setGridDensityPersist = (next: GridDensity) => {
    setGridDensity(next);
    writeGridDensity(next);
  };

  // Load the persisted page size once on mount, mirroring the view-mode load
  // (F51). A return visit reopens on the density you last picked instead of
  // snapping back to 50. Storage failures leave the in-state default intact.
  useEffect(() => {
    try {
      setLimit(parseShotsPageSize(window.localStorage.getItem(SHOTS_PAGE_SIZE_STORAGE_KEY)));
    } catch {
      // Storage blocked -- stay on the 50-row default.
    }
  }, []);

  // Change + persist the page size together so the next visit reopens here.
  const setLimitPersist = (next: ShotsPageSize) => {
    setLimit(next);
    writeShotsPageSize(next);
  };

  // Reflect the active filter into the browser tab title (F58) so a filtered
  // or deep-linked shots tab is identifiable in the tab bar -- "Receipt ·
  // >=90% confidence · Shots". Uses the debounced search / tag so the title
  // doesn't thrash on every keystroke. Restores the document's prior title on
  // unmount so navigating away doesn't leave a stale shots title behind.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const prev = document.title;
    document.title = shotsDocTitle({
      category: cat || undefined,
      q: qDebounced || undefined,
      tag: tagDebounced || undefined,
      minConfPct,
      since: since || undefined,
      until: until || undefined,
      pinnedOnly,
    });
    return () => {
      document.title = prev;
    };
  }, [cat, qDebounced, tagDebounced, minConfPct, since, until, pinnedOnly]);

  // Apply deep-link query params ONCE on mount so links INTO the list land
  // pre-filtered: the stats class-mix chips (`?category=receipt`), the
  // pinned quick-bar's "View all" (`?pinned=true`), the legend popovers, etc.
  // Historically the page ignored its own URL; now it seeds initial filter
  // state from validated params. The guard ref keeps a later in-app filter
  // change from being clobbered if the effect ever re-ran. We clear the
  // params from the URL afterwards (replace, no scroll) so a manual filter
  // tweak isn't fighting a stale query string the user can no longer see.
  const deepLinkApplied = useRef(false);
  useEffect(() => {
    if (deepLinkApplied.current) return;
    deepLinkApplied.current = true;
    const link = parseShotsDeepLink(searchParams);
    if (!hasDeepLink(link)) return;
    if (link.category !== undefined) setCat(link.category);
    if (link.q !== undefined) setQ(link.q);
    if (link.tag !== undefined) setTag(link.tag);
    if (link.minConfPct !== undefined) setMinConfPct(link.minConfPct);
    if (link.since !== undefined) setSince(link.since);
    if (link.until !== undefined) setUntil(link.until);
    if (link.sort !== undefined) setSort(link.sort);
    if (link.pinnedOnly !== undefined) setPinnedOnly(link.pinnedOnly);
    setPage(0);
    router.replace("/shots", { scroll: false });
  }, [searchParams, router]);

  const setViewPersist = (next: ShotsViewMode) => {
    setView(next);
    try {
      window.localStorage.setItem(SHOTS_VIEW_STORAGE_KEY, next);
    } catch {
      // Ignore quota / privacy-mode errors.
    }
  };

  // "v" cycles the list view (Table -> Grid -> Compact), matching the
  // discoverable shortcut now listed in the ? help overlay under "On the
  // shots list". Mirrors HotKeys' input-guard so typing "v" in the OCR
  // search box never flips the layout, and skips when a modifier is held so
  // it never collides with Cmd/Ctrl-V paste. Uses the functional setView so
  // the listener stays correct without re-binding on every view change.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      if (e.key.toLowerCase() !== "v") return;
      e.preventDefault();
      setView((cur) => {
        const next = nextViewMode(cur);
        try {
          window.localStorage.setItem(SHOTS_VIEW_STORAGE_KEY, next);
        } catch {
          // Ignore quota / privacy-mode errors.
        }
        return next;
      });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // "d" cycles the grid column density (Roomy -> Default -> Dense), mirroring
  // the "v" view cycle and only meaningful in the grid view. Two guards beyond
  // the usual input/modifier checks (F63):
  //   1. View guard -- density is a grid-only concept, so we no-op in
  //      table/compact. Read from a ref so the listener never re-binds.
  //   2. Chord guard -- `g d` is the new "go to Demo" section chord (F61). The
  //      keystroke that completes it also reaches this bare-`d` handler, so we
  //      skip a `d` that lands within the chord window after a `g`, letting
  //      HotKeys own the navigation without us flipping density on the way out.
  const viewRef = useRef<ShotsViewMode>(view);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);
  useEffect(() => {
    let lastGAt = 0;
    const CHORD_WINDOW_MS = 1200; // matches createSequenceTracker's default
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      const k = e.key.toLowerCase();
      if (k === "g") {
        lastGAt = e.timeStamp || performance.now();
        return;
      }
      if (k !== "d") return;
      // Tail of the `g d` chord -> let HotKeys navigate; don't cycle density.
      const now = e.timeStamp || performance.now();
      if (now - lastGAt <= CHORD_WINDOW_MS) {
        lastGAt = 0;
        return;
      }
      // Density only applies to the grid view.
      if (viewRef.current !== "grid") return;
      e.preventDefault();
      setGridDensity((cur) => {
        const next = nextGridDensity(cur);
        writeGridDensity(next);
        return next;
      });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // "o" toggles the inline preview (F84) of the focused row -- or the first
  // visible row when focus isn't on a row -- so the drawer is reachable from
  // the keyboard. Mirrors the "v" / "d" handlers: input-guarded so typing "o"
  // in the OCR search box never fires, and modifier-skipped so Cmd/Ctrl-O
  // (open file) is untouched. Reads the current page's ids off a ref so the
  // listener binds once. The focused row is found by walking up from
  // document.activeElement to the nearest [data-shot-id]; pickPreviewTarget
  // applies the focused-else-first rule and ignores a stale (paged-away) id.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      if (e.key.toLowerCase() !== "o") return;
      const ids = visibleIdsRef.current;
      if (ids.length === 0) return;
      const active =
        typeof document !== "undefined"
          ? (document.activeElement as HTMLElement | null)
          : null;
      const focusedId =
        active?.closest<HTMLElement>("[data-shot-id]")?.dataset.shotId ?? null;
      const target = pickPreviewTarget(focusedId, ids);
      if (!target) return;
      e.preventDefault();
      toggleExpanded(target);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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

  // Clear a single active filter by key -- backs the FilterBreadcrumb pills.
  const clearOne = (key: FilterKey) => {
    switch (key) {
      case "category":
        setCat("");
        break;
      case "q":
        setQ("");
        break;
      case "tag":
        setTag("");
        break;
      case "minConf":
        setMinConfPct(0);
        break;
      case "since":
        setSince("");
        break;
      case "until":
        setUntil("");
        break;
      case "pinned":
        setPinnedOnly(false);
        break;
    }
    setPage(0);
  };

  const resetAllFilters = () => {
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
      toast.success(
        `${verb} ${json.affected} shot${json.affected === 1 ? "" : "s"}${
          json.missing?.length ? `, ${json.missing.length} skipped` : ""
        }.`,
      );
      if (action === "delete") setBulk(new Set());
      setTagInput("");
      await reloadHistory();
    } catch (e) {
      toast.error((e as Error).message || "Bulk action failed.");
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
      toast.success(want ? "Shot pinned." : "Shot unpinned.");
    } catch (e) {
      toast.error((e as Error).message || "Pin failed.");
    }
  }

  const total = payload?.total ?? 0;

  // Build export-shaped rows for the bulk "copy as JSON / Markdown" (F35)
  // from the selected ids that are present on the current page. A selection
  // can span pages, so we can only serialise the rows we actually hold; the
  // toast names the copied-vs-selected split honestly. Preserves the on-page
  // order so the manifest reads top-to-bottom.
  const bulkExportShots: ShotExportInput[] = useMemo(() => {
    if (bulk.size === 0 || !Array.isArray(data)) return [];
    return (data as Row[])
      .filter((r) => bulk.has(r.id))
      .map((r) => ({
        id: r.id,
        filename: r.filename,
        created_at: r.created_at,
        primary_category: r.primary_category,
        confidence: r.confidence,
        elapsed_ms: r.elapsed_ms ?? null,
        source: r.source ?? null,
        label: r.label ?? null,
        tags: r.tags ?? [],
      }));
  }, [bulk, data]);

  const isSample = !!error || !Array.isArray(data) || data.length === 0;
  const sampleRows = (makeSampleShots(Math.min(limit, 60)) as unknown as Row[]).filter(
    (r) => (cat ? r.primary_category === cat : true)
  );
  const rows: Row[] = isSample && page === 0 ? sampleRows : (Array.isArray(data) ? (data as Row[]) : []);
  // Keep the bind-once `o` handler (F118) pointed at the current page's ids.
  // Assigning a fresh array each render is idempotent and cheap.
  visibleIdsRef.current = rows.map((r) => r.id);
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
            {/* Shared count-label helpers (F122) so the header range / bare
                count agree with every other count phrase in the app. */}
            {rangeOfTotalLabel(showingFrom, showingTo, effectiveTotal) ??
              countLabel(rows.length, "row")}
          </span>
          <div
            className="inline-flex items-center rounded-sm border overflow-hidden"
            style={{ borderColor: "var(--color-rule)" }}
            role="group"
            aria-label="View mode"
          >
            {SHOTS_VIEW_MODES.map((m) => {
              const Icon = m === "table" ? Table : m === "grid" ? GridFour : Rows;
              const active = view === m;
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => setViewPersist(m)}
                  aria-pressed={active}
                  aria-label={`${labelForViewMode(m)} view`}
                  title={`${labelForViewMode(m)} view`}
                  className="inline-flex items-center justify-center w-7 h-7 transition-colors"
                  style={{
                    background: active ? "var(--color-felt)" : "transparent",
                    color: active ? "var(--color-chalk)" : "var(--color-ink)",
                  }}
                >
                  <Icon size={15} weight="duotone" />
                </button>
              );
            })}
          </div>

          {/* Column-density control (F29) -- only meaningful in the grid
              view, so it appears only when grid is active. Trades card size
              for scan-density; persisted across visits. */}
          {view === "grid" && (
            <div
              className="inline-flex items-center rounded-sm border overflow-hidden"
              style={{ borderColor: "var(--color-rule)" }}
              role="group"
              aria-label="Grid density"
            >
              {GRID_DENSITIES.map((d) => {
                const active = gridDensity === d;
                const glyph =
                  d === "roomy" ? "▢" : d === "default" ? "▦" : "▩";
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setGridDensityPersist(d)}
                    aria-pressed={active}
                    aria-label={`${labelForGridDensity(d)} density`}
                    title={`${labelForGridDensity(d)} density`}
                    className="inline-flex items-center justify-center w-7 h-7 text-[13px] transition-colors"
                    style={{
                      background: active ? "var(--color-felt)" : "transparent",
                      color: active ? "var(--color-chalk)" : "var(--color-ink)",
                    }}
                  >
                    {glyph}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </header>

      <div
        className="panel p-3 flex flex-wrap items-center gap-3"
        role="toolbar"
        aria-label="Filters"
      >
        {(() => {
          // Compact active-filter count pill (F91): a quick "3 filters" signal
          // so a scrolled/narrowed toolbar still reads as filtered at a glance.
          // Reuses the same active-filter rules the breadcrumb + query use.
          const label = filterCountLabel({
            category: cat || undefined,
            q: qDebounced || undefined,
            tag: tagDebounced || undefined,
            minConfPct,
            since: since || undefined,
            until: until || undefined,
            pinnedOnly,
          });
          if (!label) return null;
          return (
            <button
              type="button"
              onClick={resetAllFilters}
              className="num inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-sm transition-opacity hover:opacity-90"
              style={{
                background: "var(--color-felt)",
                color: "var(--color-chalk)",
              }}
              aria-label={`${label} active. Clear all filters.`}
              title="Clear all filters"
              data-testid="shots-filter-count"
            >
              <Funnel size={11} weight="fill" />
              {label}
            </button>
          );
        })()}
        <select
          className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white"
          style={{ borderColor: "var(--color-rule)" }}
          value={cat}
          onChange={(e) => setCat(e.target.value as any)}
          aria-label="Filter by class"
          tabIndex={filterTabIndex("class")}
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
          aria-label="Search OCR text or filename"
          tabIndex={filterTabIndex("search")}
        />

        <select
          className="num text-[12px] px-2 py-1.5 rounded-sm border bg-white"
          style={{ borderColor: "var(--color-rule)" }}
          value={limit}
          onChange={(e) => setLimitPersist(Number(e.target.value) as ShotsPageSize)}
          aria-label="Page size"
          tabIndex={filterTabIndex("pageSize")}
        >
          {SHOTS_PAGE_SIZES.map((n) => (
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
          tabIndex={filterTabIndex("sort")}
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
            tabIndex={filterTabIndex("tag")}
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
            tabIndex={filterTabIndex("from")}
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
            tabIndex={filterTabIndex("to")}
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
            tabIndex={filterTabIndex("minConf")}
          />
          <span
            className="num text-[11px] w-[60px] text-right tabular-nums"
            title={minConfPct > 0 ? `Showing shots at or above ${minConfPct}% confidence` : "No confidence floor"}
          >
            {confFloorReadout(minConfPct)}
          </span>
        </label>

        <button
          type="button"
          className="btn btn-ghost text-[12px]"
          aria-pressed={pinnedOnly}
          onClick={() => setPinnedOnly((v) => !v)}
          title={pinnedOnly ? "Show every shot" : "Show only pinned shots"}
          tabIndex={filterTabIndex("pinned")}
          style={pinnedOnly ? { color: "#b45309" } : undefined}
        >
          <Star size={14} weight={pinnedOnly ? "fill" : "duotone"} /> Pinned
          {pinnedOnly ? " only" : ""}
        </button>

        <button
          className="btn btn-ghost"
          onClick={resetAllFilters}
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

        <div className="ml-auto flex items-center gap-2">
          {/* Expand / collapse every visible row's preview at once (F119).
              Shown only with real rows (sample data has nothing to fetch).
              The label flips to whichever action does something; off-page
              expanded previews are preserved. */}
          {!isSample &&
            rows.length > 0 &&
            (() => {
              const ids = rows.map((r) => r.id);
              const label = previewToggleAllLabel(expanded, ids);
              if (!label) return null;
              const allOpen = allPreviewsExpanded(expanded, ids);
              return (
                <button
                  type="button"
                  className="btn btn-ghost text-[12px]"
                  onClick={() => toggleAllPreviews(ids)}
                  aria-label={label}
                  title={label}
                  data-testid="shots-toggle-all-previews"
                >
                  {allOpen ? (
                    <CaretDown size={13} weight="bold" />
                  ) : (
                    <CaretRight size={13} weight="bold" />
                  )}
                  {allOpen ? "Collapse all" : "Expand all"}
                </button>
              );
            })()}
          <CopyViewLinkButton
            filters={{
              category: cat || undefined,
              q: qDebounced || undefined,
              tag: tagDebounced || undefined,
              minConfPct,
              since: since || undefined,
              until: until || undefined,
              sort,
              pinnedOnly,
            }}
            disabled={isSample}
          />
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

      <FilterBreadcrumb
        filters={{
          category: cat || undefined,
          q: qDebounced || undefined,
          tag: tagDebounced || undefined,
          minConfPct,
          since: since || undefined,
          until: until || undefined,
          pinnedOnly,
        }}
        onClear={clearOne}
        onClearAll={resetAllFilters}
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
          <div className="ml-auto flex items-center gap-2">
            <span
              className="eyebrow opacity-60 hidden sm:inline"
              aria-hidden
            >
              Export
            </span>
            <BulkExportButtons
              shots={bulkExportShots}
              selectedCount={bulk.size}
              disabled={bulkBusy}
            />
          </div>
        </div>
      )}

      <div className="panel overflow-hidden">
        {isLoading && !rows.length ? (
          <div className="p-3" aria-label="Loading shots" role="status" aria-busy="true">
            <SkeletonRows rows={8} />
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
                        onClick: resetAllFilters,
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
        ) : !isTabular(view) ? (
          <ShotGrid
            rows={rows}
            bulk={bulk}
            picked={picked}
            isSample={isSample}
            density={gridDensity}
            expanded={expanded}
            onToggleBulk={toggleBulk}
            onTogglePick={togglePick}
            onTogglePin={(r) => void togglePin(r as Row)}
            onTagClick={(t) => setTag(t)}
            onToggleExpand={toggleExpanded}
          />
        ) : (
          <div className="overflow-auto max-h-[70vh]">
            <table className={isCompact(view) ? "tbl tbl-compact" : "tbl"}>
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
                  <th className="w-[40px]">
                    <span
                      className="inline-flex items-center justify-center opacity-45"
                      title="Copy a row as JSON, Markdown, or CSV"
                      aria-label="Row export"
                    >
                      <DotsThreeOutline size={13} weight="duotone" aria-hidden />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                  <tr data-picked={picked.includes(r.id)} data-shot-id={r.id}>
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
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => toggleExpanded(r.id)}
                          aria-expanded={expanded.has(r.id)}
                          aria-label={
                            expanded.has(r.id)
                              ? `Collapse preview of ${shortId(r.id)}`
                              : `Preview ${shortId(r.id)} inline`
                          }
                          title={expanded.has(r.id) ? "Hide preview" : "Quick preview"}
                          className="inline-flex items-center justify-center w-5 h-5 rounded-sm hover:bg-black/[0.06] text-[color:rgba(0,0,0,0.4)]"
                        >
                          {expanded.has(r.id) ? (
                            <CaretDown size={13} weight="bold" />
                          ) : (
                            <CaretRight size={13} weight="bold" />
                          )}
                        </button>
                        <Link
                          href={`/shots/${r.id}`}
                          className="num text-[12px] hover:text-[color:var(--color-felt)]"
                        >
                          {shortId(r.id)}
                        </Link>
                      </div>
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
                    <td>
                      {/* Per-row "Copy as ..." trio (F97/F94) -- grab one
                          shot's JSON / Markdown / CSV without opening it,
                          reusing the shared EXPORT_FORMATS + serializers so the
                          list, detail, and bulk surfaces stay in lockstep. The
                          export shape comes from shotRowToExportInput so the
                          table + grid feed RowExportMenu identical data (F109). */}
                      <RowExportMenu
                        shortId={shortId(r.id)}
                        disabled={isSample}
                        shot={shotRowToExportInput(r)}
                      />
                    </td>
                  </tr>
                  {expanded.has(r.id) && (
                    <ShotPreviewRow id={r.id} colSpan={11} />
                  )}
                  </Fragment>
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

// useSearchParams() must render under a Suspense boundary in the Next App
// Router. The inner component holds all the page logic; this thin wrapper
// supplies the boundary with a lightweight loading shell.
export default function ShotsPage() {
  return (
    <Suspense
      fallback={
        <div
          className="p-3"
          aria-label="Loading shots"
          role="status"
          aria-busy="true"
        >
          <SkeletonRows rows={8} />
        </div>
      }
    >
      <ShotsPageInner />
    </Suspense>
  );
}
