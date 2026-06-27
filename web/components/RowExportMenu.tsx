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
        >
          {EXPORT_FORMATS.map((f) => (
            <button
              key={f.key}
              role="menuitem"
              type="button"
              className="num w-full text-left px-2.5 py-1.5 text-[12px] hover:bg-black/5 rounded-sm flex items-center gap-2"
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
