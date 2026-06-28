"use client";

// ShotGrid: the card-grid rendering mode for /shots (F10). Each card shows
// the category chip, a confidence badge, the file/label, when it landed,
// and up to a few tags -- a more scannable, OCR-forward alternative to the
// dense table. Bulk-select + compare + pin stay available via small
// overlay controls so the grid is not a read-only downgrade. The page owns
// data + state; this component is a pure presenter over the same Row shape.

import Link from "next/link";
import { Star, CheckSquare, Square, Scales, CaretDown, CaretRight } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { ConfBadge } from "@/components/ConfBadge";
import RowExportMenu from "@/components/RowExportMenu";
import { ShotPreviewCardRow } from "@/components/ShotPreviewDrawer";
import { ms, shortId, type Category } from "@/lib/categories";
import { shotRowToExportInput } from "@/lib/shot-export";
import {
  gridColumnsClass,
  GRID_DENSITY_DEFAULT,
  type GridDensity,
} from "@/lib/grid-density";

export type ShotGridRow = {
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
  });
}

export function ShotGrid({
  rows,
  bulk,
  picked,
  isSample,
  density = GRID_DENSITY_DEFAULT,
  expanded,
  onToggleBulk,
  onTogglePick,
  onTogglePin,
  onTagClick,
  onToggleExpand,
}: {
  rows: ShotGridRow[];
  bulk: Set<string>;
  picked: string[];
  isSample: boolean;
  density?: GridDensity;
  // Ids whose inline preview card is open (F117). Optional so callers that
  // don't wire previews (none today, but keeps the contract additive) degrade
  // to no expand affordance.
  expanded?: Set<string>;
  onToggleBulk: (id: string) => void;
  onTogglePick: (id: string) => void;
  onTogglePin: (row: ShotGridRow) => void;
  onTagClick: (tag: string) => void;
  onToggleExpand?: (id: string) => void;
}) {
  const canPreview = !!onToggleExpand;
  return (
    <ul
      className={`grid ${gridColumnsClass(density)} gap-3 p-3`}
      data-testid="shots-grid"
      data-density={density}
    >
      {rows.map((r) => {
        const selected = bulk.has(r.id);
        const isPicked = picked.includes(r.id);
        const isExpanded = !!expanded?.has(r.id);
        const name = (r.label && r.label.trim()) || r.filename;
        return (
          <li
            key={r.id}
            className="panel p-3 flex flex-col gap-2 relative transition-shadow hover:shadow-md"
            data-picked={isPicked}
            data-shot-id={r.id}
            style={
              isPicked
                ? { outline: "2px solid var(--color-felt)", outlineOffset: -1 }
                : undefined
            }
          >
            <div className="flex items-center justify-between gap-2">
              <Chip cat={r.primary_category} />
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => onToggleBulk(r.id)}
                  disabled={isSample}
                  className="inline-flex items-center justify-center w-6 h-6 rounded-sm hover:bg-black/[0.05]"
                  aria-label={
                    selected
                      ? `Deselect ${shortId(r.id)}`
                      : `Select ${shortId(r.id)} for bulk actions`
                  }
                  aria-pressed={selected}
                  title={selected ? "Selected" : "Select for bulk actions"}
                >
                  {selected ? (
                    <CheckSquare size={16} weight="duotone" />
                  ) : (
                    <Square size={16} weight="duotone" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => onTogglePin(r)}
                  disabled={isSample}
                  className="inline-flex items-center justify-center w-6 h-6 rounded-sm hover:bg-black/[0.05]"
                  aria-label={r.pinned ? `Unpin ${shortId(r.id)}` : `Pin ${shortId(r.id)}`}
                  aria-pressed={!!r.pinned}
                  title={r.pinned ? "Pinned. Click to unpin." : "Pin this shot"}
                  style={r.pinned ? { color: "#b45309" } : { color: "rgba(0,0,0,0.35)" }}
                >
                  <Star size={15} weight={r.pinned ? "fill" : "duotone"} />
                </button>
              </div>
            </div>

            <Link href={`/shots/${r.id}`} className="group flex flex-col gap-1">
              <span
                className="text-[13px] font-medium truncate group-hover:text-[color:var(--color-felt)]"
                title={name}
              >
                {name}
              </span>
              <span className="num text-[10px] opacity-55">
                {shortId(r.id)} · {r.source ?? "api"}
              </span>
            </Link>

            <div className="flex items-center justify-between gap-2">
              <ConfBadge score={r.confidence} size="sm" variant="ghost" digits={1} />
              <span className="num text-[10px] opacity-60">
                {r.elapsed_ms != null ? ms(r.elapsed_ms) : "—"}
              </span>
            </div>

            {r.tags && r.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {r.tags.slice(0, 4).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => onTagClick(t)}
                    className="num text-[10px] px-1.5 py-[1px] rounded-sm border border-black/15 bg-black/[0.03] hover:bg-black/[0.06]"
                    title={`Filter by tag: ${t}`}
                  >
                    {t}
                  </button>
                ))}
                {r.tags.length > 4 && (
                  <span className="num text-[10px] opacity-50">+{r.tags.length - 4}</span>
                )}
              </div>
            )}

            <div className="flex items-center justify-between gap-2 mt-auto pt-1 border-t" style={{ borderColor: "var(--color-rule)" }}>
              <span className="num text-[10px] opacity-55 whitespace-nowrap">
                {fmtTime(r.created_at)}
              </span>
              <div className="flex items-center gap-1">
                {/* Inline preview toggle (F117) -- opens the same drawer body
                    the table row offers, dropped below this card. Only shown
                    when the page wired the preview callbacks. */}
                {canPreview && (
                  <button
                    type="button"
                    onClick={() => onToggleExpand!(r.id)}
                    aria-expanded={isExpanded}
                    aria-label={
                      isExpanded
                        ? `Collapse preview of ${shortId(r.id)}`
                        : `Preview ${shortId(r.id)} inline`
                    }
                    title={isExpanded ? "Hide preview" : "Quick preview"}
                    className="inline-flex items-center gap-1 text-[10px] eyebrow opacity-70 hover:opacity-100"
                    style={isExpanded ? { color: "var(--color-felt)" } : undefined}
                  >
                    {isExpanded ? (
                      <CaretDown size={12} weight="bold" />
                    ) : (
                      <CaretRight size={12} weight="bold" />
                    )}
                    Preview
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => onTogglePick(r.id)}
                  className="inline-flex items-center gap-1 text-[10px] eyebrow opacity-70 hover:opacity-100"
                  aria-label={
                    isPicked
                      ? `Remove ${shortId(r.id)} from compare`
                      : `Add ${shortId(r.id)} to compare`
                  }
                  aria-pressed={isPicked}
                  title={isPicked ? "Selected for compare" : "Select to compare"}
                  style={isPicked ? { color: "var(--color-felt)" } : undefined}
                >
                  <Scales size={12} weight="duotone" />
                  {isPicked ? "Picked" : "Compare"}
                </button>
                {/* Per-row "Copy as ..." trio (F109) -- the same one-shot
                    JSON / Markdown / CSV grab the table row offers, now on the
                    grid card too. shotRowToExportInput keeps the export shape
                    byte-identical across all three list layouts. */}
                <RowExportMenu
                  shortId={shortId(r.id)}
                  disabled={isSample}
                  shot={shotRowToExportInput(r)}
                />
              </div>
            </div>
            {/* Inline preview card (F117): the lazy-fetching wrapper only
                mounts while this card is expanded, so no detail request fires
                until the user opens it. Shares ShotPreviewBody with the table
                drawer so both layouts read identically. */}
            {canPreview && isExpanded && <ShotPreviewCardRow id={r.id} />}
          </li>
        );
      })}
    </ul>
  );
}

export default ShotGrid;
