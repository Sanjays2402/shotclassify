"use client";

// Bulk "copy as JSON / Markdown" buttons for the /shots multi-select (F35).
// Reuses lib/shot-export-bulk serializers (which themselves reuse the single-
// shot lib/shot-export). Sits in the bulk-actions bar; copies a manifest of
// the rows currently held for the selection and toasts the result, honest
// about the selected-vs-copied split when the selection spans pages.

import { useState } from "react";
import { BracketsCurly, MarkdownLogo, Table } from "@phosphor-icons/react/dist/ssr";
import {
  toBulkJson,
  toBulkMarkdown,
  toBulkCsv,
  bulkExportToastMessage,
} from "@/lib/shot-export-bulk";
import type { ShotExportInput } from "@/lib/shot-export";
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

  async function copy(format: "JSON" | "Markdown" | "CSV") {
    if (busy) return;
    setBusy(true);
    try {
      const text =
        format === "JSON"
          ? toBulkJson(shots)
          : format === "Markdown"
            ? toBulkMarkdown(shots)
            : toBulkCsv(shots);
      await writeClipboard(text);
      const msg = bulkExportToastMessage(shots.length, selectedCount, format);
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
      <button
        type="button"
        className="btn btn-ghost text-[12px]"
        disabled={off}
        onClick={() => void copy("JSON")}
        aria-label="Copy the selected shots as a JSON array"
        title="Copy the selected shots as a JSON array"
      >
        <BracketsCurly size={14} weight="duotone" /> Copy JSON
      </button>
      <button
        type="button"
        className="btn btn-ghost text-[12px]"
        disabled={off}
        onClick={() => void copy("Markdown")}
        aria-label="Copy the selected shots as a Markdown table"
        title="Copy the selected shots as a Markdown table"
      >
        <MarkdownLogo size={14} weight="duotone" /> Copy MD
      </button>
      <button
        type="button"
        className="btn btn-ghost text-[12px]"
        disabled={off}
        onClick={() => void copy("CSV")}
        aria-label="Copy the selected shots as a CSV spreadsheet"
        title="Copy the selected shots as RFC-4180 CSV (opens in any spreadsheet)"
      >
        <Table size={14} weight="duotone" /> Copy CSV
      </button>
    </div>
  );
}
