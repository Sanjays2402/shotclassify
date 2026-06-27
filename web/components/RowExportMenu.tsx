"use client";

// Per-row "Copy as ..." export menu for the /shots table (F97/F94). The
// shot-detail page can already copy ONE shot as JSON / Markdown / CSV
// (CopyExportButtons) and the bulk bar copies a selection (BulkExportButtons);
// this brings the same trio to a single list row so you can grab one shot's
// export without opening it. It reuses the shared EXPORT_FORMATS catalogue +
// the single-shot serializers (toJson / toMarkdown / toCsv), so the list,
// detail, and bulk surfaces can never expose a different set of formats (F86).
//
// A compact icon button opens a small dropdown of the three formats; copying
// reports via the app toast primitive. Outside-click + Escape close it,
// mirroring ExportMenu. Presentation-only beyond the clipboard write -- no new
// endpoint, the row data already holds everything the serializers need.

import { useEffect, useRef, useState } from "react";
import {
  DotsThreeOutline,
  BracketsCurly,
  MarkdownLogo,
  Table,
} from "@phosphor-icons/react/dist/ssr";
import {
  toJson,
  toMarkdown,
  toCsv,
  EXPORT_FORMATS,
  type ExportFormatKey,
  type ShotExportInput,
} from "@/lib/shot-export";
import { rovingIndex, isRovingKey } from "@/lib/roving-index";
import { toast } from "@/lib/toast-store";

// Clipboard write with a non-secure-context fallback, mirroring
// CopyExportButtons / BulkExportButtons so http dev / older Safari still copy.
async function writeClipboard(text: string): Promise<void> {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard &&
    typeof window !== "undefined" &&
    window.isSecureContext
  ) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

const ICONS: Record<ExportFormatKey, React.ReactNode> = {
  json: <BracketsCurly size={14} weight="duotone" />,
  markdown: <MarkdownLogo size={14} weight="duotone" />,
  csv: <Table size={14} weight="duotone" />,
};

function serialize(format: ExportFormatKey, shot: ShotExportInput): string {
  if (format === "json") return toJson(shot);
  if (format === "markdown") return toMarkdown(shot);
  return toCsv(shot);
}

export default function RowExportMenu({
  shot,
  shortId,
  disabled,
}: {
  // The export-shaped row this menu copies.
  shot: ShotExportInput;
  // A short id for the toast / aria so a copy from a dense table is traceable.
  shortId: string;
  // Disabled on the sample/preview data (there's nothing real to copy).
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  // Roving focus for keyboard navigation (F114): which menu item is active.
  // -1 = "nothing focused yet" so the first ArrowDown lands on the top item.
  const [activeIndex, setActiveIndex] = useState(-1);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

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

  // On open, prime the roving focus to the first item; on close, reset it so
  // the next open starts clean. Move actual DOM focus when the active index
  // changes while open so Arrow keys visibly walk the list.
  useEffect(() => {
    if (open) setActiveIndex(0);
    else setActiveIndex(-1);
  }, [open]);

  useEffect(() => {
    if (!open || activeIndex < 0) return;
    itemRefs.current[activeIndex]?.focus();
  }, [open, activeIndex]);

  // Arrow / Home / End navigation between the format items. Enter / Space fire
  // the focused item via the button's native activation; Escape is handled by
  // the document listener above. preventDefault on a handled nav key stops the
  // dropdown from scrolling the table behind it.
  function onMenuKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (!isRovingKey(e.key)) return;
    const next = rovingIndex(activeIndex, EXPORT_FORMATS.length, e.key);
    if (next == null) return;
    e.preventDefault();
    setActiveIndex(next);
  }

  async function copy(format: ExportFormatKey, noun: string) {
    try {
      await writeClipboard(serialize(format, shot));
      toast.success(`Copied ${shortId} as ${noun}.`);
    } catch {
      toast.error("Copy failed. Your browser blocked clipboard access.");
    } finally {
      setOpen(false);
    }
  }

  return (
    <div ref={wrapRef} className="relative inline-flex">
      <button
        type="button"
        className="inline-flex items-center justify-center w-6 h-6 rounded-sm hover:bg-black/[0.06] disabled:opacity-30"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Copy ${shortId} as JSON, Markdown, or CSV`}
        title="Copy as JSON / Markdown / CSV"
        disabled={disabled}
        onClick={(e) => {
          e.preventDefault();
          setOpen((v) => !v);
        }}
      >
        <DotsThreeOutline size={14} weight="duotone" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 z-20 min-w-[150px] panel p-1 shadow-lg bg-white"
          style={{ borderColor: "var(--color-rule)" }}
          onKeyDown={onMenuKeyDown}
        >
          {EXPORT_FORMATS.map((f, i) => (
            <button
              key={f.key}
              ref={(el) => {
                itemRefs.current[i] = el;
              }}
              role="menuitem"
              type="button"
              // Roving tabindex: only the active item is in the tab order so
              // Tab leaves the menu instead of walking each item (F114).
              tabIndex={activeIndex === i ? 0 : -1}
              className="num w-full text-left px-2.5 py-1.5 text-[12px] hover:bg-black/5 focus:bg-black/5 focus:outline-none rounded-sm flex items-center gap-2"
              onClick={(e) => {
                e.preventDefault();
                void copy(f.key, f.noun);
              }}
            >
              {ICONS[f.key]}
              <span>Copy {f.noun}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
