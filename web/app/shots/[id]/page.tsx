"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";
import { Star } from "@phosphor-icons/react/dist/ssr";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import { SampleBadge } from "@/components/SampleBadge";
import { UmpireControls } from "@/components/UmpireControls";
import LabelTagsEditor from "@/components/LabelTagsEditor";
import ShareActions from "@/components/ShareActions";
import CopyExportButtons from "@/components/CopyExportButtons";
import ShotNav from "@/components/ShotNav";
import { CollapsibleSection } from "@/components/CollapsibleSection";
import { useChartTheme } from "@/components/useChartTheme";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { recordRecentShot } from "@/lib/recent-shots";
import {
  readDetailRail,
  writeDetailRail,
  clearDetailRail,
  toggleSlot,
  isCollapsed,
  allCollapsed,
  allExpanded,
  collapseAll,
  expandAll,
  railChordAction,
  type DetailRailState,
  type DetailRailSlot,
} from "@/lib/detail-rail";
import {
  CATEGORIES,
  LONG,
  SHORT,
  confColor,
  ms,
  pct,
  shortId,
  type Category,
} from "@/lib/categories";
import { makeSampleShots, sampleDistribution } from "@/lib/sample";

type Detail = {
  id: string;
  filename: string;
  created_at: string;
  primary_category: Category;
  confidence: number;
  elapsed_ms?: number;
  source?: string;
  ocr_text?: string;
  image_path?: string | null;
  user_corrected_to?: Category | null;
  label?: string | null;
  tags?: string[];
  pinned?: boolean;
  // Server may also include richer fields.
  classification?: {
    primary: Category;
    confidences: { category: Category; score: number }[];
    rationale?: string;
  };
  ocr?: { text: string; word_count?: number; mean_confidence?: number };
};

function fmt(iso: string) {
  return new Date(iso).toLocaleString();
}

export default function ShotDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { mutate: globalMutate } = useSWRConfig();
  const [pinBusy, setPinBusy] = useState(false);
  const [mounted, setMounted] = useState(false);
  // Per-slot collapse state for the right rail (F77). Empty (all expanded)
  // until the mount effect loads any persisted folds, so SSR and the first
  // client render agree. A toggle persists the whole set so a return visit
  // reopens with the same sections folded.
  const [rail, setRail] = useState<DetailRailState>(new Set());
  const chart = useChartTheme();
  useEffect(() => {
    setMounted(true);
    setRail(readDetailRail());
  }, []);

  const toggleRail = (slot: DetailRailSlot) => {
    setRail((cur) => {
      const next = toggleSlot(cur, slot);
      writeDetailRail(next);
      return next;
    });
  };

  // Fold or unfold every rail section at once (F82). Writes the full set so
  // the choice persists like an individual toggle does. The header control
  // decides which action to offer from the current state.
  const setAllRail = (collapsed: boolean) => {
    const next = collapsed ? collapseAll() : expandAll();
    writeDetailRail(next);
    setRail(next);
  };

  // Reset the rail to its friendly all-expanded default AND forget the
  // persisted folds (F105). Distinct from "Expand all", which persists an
  // explicit empty blob -- this removes the stored key entirely, so the rail
  // behaves like a brand-new visitor's on the next visit. Only offered when
  // something is actually folded (see the control's render guard).
  const resetRail = () => {
    clearDetailRail();
    setRail(expandAll());
  };

  // Keyboard chords for the rail (F93): Shift+E expands every section, Shift+C
  // collapses every section -- registered under the "detail" scope in the ?
  // overlay so they self-document. Input-guarded so typing into the tag editor
  // never folds the rail. railChordAction (pure, requires shift, forbids
  // Cmd/Ctrl/Alt) keeps the matching testable; HotKeys' bare-letter nav now
  // skips Shift-held keys, so Shift+C won't ALSO route to /calibration.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      const action = railChordAction(e);
      if (action === "expand") {
        e.preventDefault();
        setAllRail(false);
      } else if (action === "collapse") {
        e.preventDefault();
        setAllRail(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const { data, error, isLoading } = useSWR<Detail>(
    ENDPOINTS.historyItem(id),
    fetcher
  );

  const notFound = !!error && (error as any).status === 404;
  const isSample = !data || notFound;

  // Sample fallback (clearly labeled).
  const sample = isSample
    ? (() => {
        const seed = makeSampleShots(1)[0];
        return {
          id,
          filename: seed.filename,
          created_at: seed.created_at,
          primary_category: seed.primary_category,
          confidence: seed.confidence,
          elapsed_ms: seed.elapsed_ms,
          source: seed.source,
          ocr_text: "lorem ipsum sample ocr text · this record is seeded",
          label: null,
          tags: [],
        } as Detail;
      })()
    : null;

  const rec = (data ?? sample)!;
  // Record this visit in the recently-viewed MRU ring (powers the command
  // palette's "recently viewed" section). Only real records -- never the
  // seeded sample shown for a 404 -- so the palette can't link to a ghost id.
  useEffect(() => {
    if (isSample || !data) return;
    recordRecentShot({
      id: data.id,
      label: (data.label && data.label.trim()) || data.filename,
      category: data.primary_category,
    });
  }, [isSample, data]);

  const dist =
    rec.classification?.confidences ??
    sampleDistribution(rec.primary_category, rec.confidence);
  const sortedDist = [...dist].sort((a, b) => b.score - a.score);
  const chartData = sortedDist.map((d) => ({
    name: SHORT[d.category],
    cat: d.category,
    score: +(d.score * 100).toFixed(2),
  }));

  // Structured payload for the copy-as-JSON / copy-as-Markdown export.
  const exportShot = {
    id: rec.id,
    filename: rec.filename,
    created_at: rec.created_at,
    primary_category: rec.primary_category,
    confidence: rec.confidence,
    elapsed_ms: rec.elapsed_ms ?? null,
    source: rec.source ?? null,
    label: rec.label ?? null,
    tags: rec.tags ?? [],
    user_corrected_to: rec.user_corrected_to ?? null,
    ocr_text: rec.ocr?.text || rec.ocr_text || null,
    rationale: rec.classification?.rationale ?? null,
    distribution: sortedDist.map((d) => ({
      category: d.category,
      score: d.score,
    })),
  };

  if (isLoading && !rec) {
    return <div className="p-6 text-sm opacity-70">Cueing up the replay…</div>;
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3 text-[12px]">
        <Link href="/shots" className="eyebrow hover:underline">
          ← All shots
        </Link>
        <span className="opacity-40">/</span>
        <span className="num">{shortId(rec.id)}</span>
        {isSample && <SampleBadge note="No record found; rendering seeded sample." />}
        {!isSample && <ShotNav currentId={rec.id} />}
        {isSample && (
          <div className="ml-auto">
            <CopyExportButtons shot={exportShot} />
          </div>
        )}
        {!isSample && (
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              disabled={pinBusy}
              onClick={async () => {
                const want = !rec.pinned;
                setPinBusy(true);
                try {
                  const res = await fetch(`/api/shots/${encodeURIComponent(rec.id)}`, {
                    method: "PATCH",
                    headers: { "content-type": "application/json" },
                    body: JSON.stringify({ pinned: want }),
                  });
                  if (!res.ok) throw new Error(await res.text());
                  await globalMutate(ENDPOINTS.historyItem(rec.id));
                  await globalMutate(
                    (key) => typeof key === "string" && key.startsWith("/api/history"),
                    undefined,
                    { revalidate: true },
                  );
                } catch {
                  // best effort; SWR retry will refetch.
                } finally {
                  setPinBusy(false);
                }
              }}
              className="btn btn-ghost text-[12px]"
              aria-pressed={!!rec.pinned}
              aria-label={rec.pinned ? "Unpin this shot" : "Pin this shot"}
              title={rec.pinned ? "Pinned. Click to unpin." : "Pin this shot"}
              style={rec.pinned ? { color: "#b45309" } : undefined}
            >
              <Star size={14} weight={rec.pinned ? "fill" : "duotone"} />
              {rec.pinned ? "Pinned" : "Pin"}
            </button>
            <CopyExportButtons shot={exportShot} />
            <ShareActions id={rec.id} />
          </div>
        )}
      </div>

      <header className="panel p-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">The call</div>
          <div className="flex items-center gap-3 mt-1">
            <Chip cat={rec.primary_category} size="lg" />
            <span
              className="num text-[28px]"
              style={{ color: confColor(rec.confidence) }}
            >
              {pct(rec.confidence, 1)}
            </span>
          </div>
          <h1 className="h-display text-[24px] mt-3 truncate max-w-[60ch]">
            {(rec.label && rec.label.trim()) || rec.filename}
          </h1>
          {rec.label && rec.label.trim() && rec.label.trim() !== rec.filename && (
            <div className="num text-[11px] opacity-60 mt-0.5 truncate max-w-[60ch]">
              file: {rec.filename}
            </div>
          )}
          <div className="num text-[11px] opacity-70 mt-1">
            {fmt(rec.created_at)} · {rec.source ?? "api"} ·{" "}
            {rec.elapsed_ms != null ? ms(rec.elapsed_ms) : "latency n/a"}
          </div>
        </div>
        {rec.user_corrected_to && (
          <div className="text-right">
            <div className="eyebrow">Corrected to</div>
            <Chip cat={rec.user_corrected_to} />
          </div>
        )}
      </header>

      <section className="grid lg:grid-cols-[1.4fr_1fr] gap-5">
        <div className="panel p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="eyebrow">Confidence distribution</span>
            <span className="num text-[11px] opacity-60">{CATEGORIES.length} classes</span>
          </div>
          <div style={{ width: "100%", height: 280 }}>
            {mounted && (
            <ResponsiveContainer>
              <BarChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                <CartesianGrid stroke={chart.gridStroke} vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: chart.tickFill }}
                  stroke={chart.axisStroke}
                />
                <YAxis
                  tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: chart.tickFill }}
                  stroke={chart.axisStroke}
                  domain={[0, 100]}
                  unit="%"
                />
                <Tooltip
                  cursor={{ fill: chart.cursorFill }}
                  contentStyle={chart.tooltip}
                  formatter={(v: any) => [`${v}%`, "score"]}
                />
                <Bar dataKey="score" radius={[2, 2, 0, 0]}>
                  {chartData.map((d) => (
                    <Cell
                      key={d.cat}
                      fill={`var(--color-cat-${d.cat.split("_")[0]})`}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            )}
          </div>

          <ul className="mt-4 flex flex-col gap-1.5">
            {sortedDist.map((d) => (
              <li
                key={d.category}
                className="grid grid-cols-[110px_1fr_64px] items-center gap-3"
              >
                <Chip cat={d.category} />
                <div style={{ ["--bar" as any]: `var(--color-cat-${d.category.split("_")[0]})` }}>
                  <ConfBar score={d.score} />
                </div>
                <span className="num text-[12px] text-right">{pct(d.score, 2)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex flex-col gap-5">
          {/* Expand all / Collapse all for the whole rail (F82). Mounted-gated
              so SSR and the first client render agree before persisted folds
              load. Offers the action that does something: when everything is
              folded it invites "Expand all", otherwise "Collapse all". */}
          {mounted && (
            <div className="flex items-center justify-end gap-1.5 -mb-2">
              {/* Reset to defaults (F105) -- clears the persisted folds so the
                  rail behaves like a first visit. Only shown when something is
                  actually folded, so it never adds inert chrome. Sits before
                  the Expand/Collapse-all control. */}
              {!allExpanded(rail) && (
                <button
                  type="button"
                  onClick={resetRail}
                  className="num text-[10px] uppercase tracking-wider opacity-45 hover:opacity-100 transition-opacity"
                  aria-label="Reset rail sections to the default (all expanded) and forget saved folds"
                  title="Forget saved folds and reopen every section"
                >
                  Reset
                </button>
              )}
              <button
                type="button"
                onClick={() => setAllRail(!allCollapsed(rail))}
                className="num text-[10px] uppercase tracking-wider opacity-55 hover:opacity-100 transition-opacity inline-flex items-center gap-1"
                aria-label={
                  allCollapsed(rail)
                    ? "Expand all rail sections"
                    : "Collapse all rail sections"
                }
                title={
                  allCollapsed(rail)
                    ? "Unfold every section (Shift+E)"
                    : "Fold every section (Shift+C)"
                }
              >
                {allCollapsed(rail) ? "Expand all" : "Collapse all"}
              </button>
              {/* Tiny chord hint so the Shift+E / Shift+C keys (F93) are
                  discoverable on-page, not just in the ? overlay. Mirrors the
                  ShotNav [ ] hint. aria-hidden because the button label +
                  title already convey the action for screen readers. */}
              <span
                className="hidden sm:inline-flex items-center gap-0.5 opacity-45"
                aria-hidden
                title="Shift+E expands every section, Shift+C collapses every section"
              >
                <kbd className="kbd text-[9px] leading-none">⇧</kbd>
                <kbd className="kbd text-[9px] leading-none">
                  {allCollapsed(rail) ? "E" : "C"}
                </kbd>
              </span>
            </div>
          )}

          <CollapsibleSection
            title="OCR transcript"
            collapsed={mounted && isCollapsed(rail, "ocr")}
            onToggle={() => toggleRail("ocr")}
          >
            <pre className="text-[12px] whitespace-pre-wrap leading-snug max-h-[260px] overflow-auto">
{rec.ocr?.text || rec.ocr_text || "(no OCR text on record)"}
            </pre>
            {rec.ocr?.word_count != null && (
              <div className="num text-[10px] opacity-60 mt-2">
                {rec.ocr.word_count} words · mean conf{" "}
                {rec.ocr.mean_confidence?.toFixed?.(2) ?? "n/a"}
              </div>
            )}
          </CollapsibleSection>

          <CollapsibleSection
            title="Rationale"
            dark
            collapsed={mounted && isCollapsed(rail, "rationale")}
            onToggle={() => toggleRail("rationale")}
          >
            <p className="text-[12px] opacity-90 leading-relaxed">
              {rec.classification?.rationale ||
                "The model called this class on visual layout, density, and OCR cues. No verbal rationale on file for this record."}
            </p>
          </CollapsibleSection>

          <CollapsibleSection
            title="Umpire review"
            collapsed={mounted && isCollapsed(rail, "umpire")}
            onToggle={() => toggleRail("umpire")}
          >
            <UmpireControls
              id={rec.id}
              primary={rec.primary_category}
              corrected={rec.user_corrected_to ?? null}
              disabled={isSample}
              embedded
            />
          </CollapsibleSection>

          <CollapsibleSection
            title="Label & tags"
            collapsed={mounted && isCollapsed(rail, "tags")}
            onToggle={() => toggleRail("tags")}
          >
            <LabelTagsEditor
              id={rec.id}
              label={rec.label ?? null}
              tags={rec.tags ?? []}
              filenameFallback={rec.filename}
              disabled={isSample}
              embedded
            />
          </CollapsibleSection>

          {rec.image_path && (
            <CollapsibleSection
              title="Frame"
              collapsed={mounted && isCollapsed(rail, "frame")}
              onToggle={() => toggleRail("frame")}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/api/proxy/v1/blobs/${rec.id}`}
                alt={rec.filename}
                className="w-full rounded-sm"
              />
            </CollapsibleSection>
          )}
        </div>
      </section>
    </div>
  );
}
