"use client";

// Bulk "copy as JSON / Markdown / CSV" buttons for the /shots multi-select
// (F35, F64). Reuses lib/shot-export-bulk serializers (which themselves reuse
// the single-shot lib/shot-export). Sits in the bulk-actions bar; copies a
// manifest of the rows currently held for the selection and toasts the
// result, honest about the selected-vs-copied split when the selection spans
// pages.
//
// The format list + labels come from the shared EXPORT_FORMATS catalogue
// (lib/shot-export) -- the same source the single-shot CopyExportButtons maps
// over -- so the two surfaces can never expose a different set of formats
// (F86). This surface uses the compact `short` label ("Copy MD") since the
// bulk bar is denser.

import { useState } from "react";
import { BracketsCurly, MarkdownLogo, Table } from "@phosphor-icons/react/dist/ssr";
import {
  toBulkJson,
  toBulkMarkdown,
  toBulkCsv,
  bulkExportToastMessage,
} from "@/lib/shot-export-bulk";
import {
  EXPORT_FORMATS,
  type ExportFormatKey,
  type ShotExportInput,
} from "@/lib/shot-export";
import { toast } from "@/lib/toast-store";

// Clipboard write with a non-secure-context fallback, mirroring
// CopyExportButtons so http dev / older Safari still copy.
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

// Per-format presentation specific to the bulk bar: icon + the bulk
// serializer. The format set / order / labels come from EXPORT_FORMATS.
const ICONS: Record<ExportFormatKey, React.ReactNode> = {
  json: <BracketsCurly size={14} weight="duotone" />,
  markdown: <MarkdownLogo size={14} weight="duotone" />,
  csv: <Table size={14} weight="duotone" />,
};

const ARIA: Record<ExportFormatKey, string> = {
  json: "Copy the selected shots as a JSON array",
  markdown: "Copy the selected shots as a Markdown table",
  csv: "Copy the selected shots as RFC-4180 CSV (opens in any spreadsheet)",
};

function serializeBulk(
  format: ExportFormatKey,
  shots: ShotExportInput[],
): string {
  if (format === "json") return toBulkJson(shots);
  if (format === "markdown") return toBulkMarkdown(shots);
  return toBulkCsv(shots);
}

export default function BulkExportButtons({
  shots,
  selectedCount,
  disabled,
}: {
  // The export-shaped rows the page currently holds for the selection.
  shots: ShotExportInput[];
  // How many ids are selected in total (may exceed shots.length across pages).
  selectedCount: number;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);

  async function copy(
    format: ExportFormatKey,
    noun: "JSON" | "Markdown" | "CSV",
  ) {
    if (busy) return;
    setBusy(true);
    try {
      const text = serializeBulk(format, shots);
      await writeClipboard(text);
      const msg = bulkExportToastMessage(shots.length, selectedCount, noun);
      if (shots.length === 0) toast.error(msg);
      else toast.success(msg);
    } catch {
      toast.error(`Copy failed. Your browser blocked clipboard access.`);
    } finally {
      setBusy(false);
    }
  }

  const off = disabled || busy || shots.length === 0;

  return (
    <div className="inline-flex items-center gap-1.5">
      {EXPORT_FORMATS.map((f) => (
        <button
          key={f.key}
          type="button"
          className="btn btn-ghost text-[12px]"
          disabled={off}
          onClick={() => void copy(f.key, f.noun)}
          aria-label={ARIA[f.key]}
          title={ARIA[f.key]}
        >
          {ICONS[f.key]} Copy {f.short}
        </button>
      ))}
    </div>
  );
}
