"use client";

// Copy-as-JSON / copy-as-Markdown / copy-as-CSV buttons for the shot detail
// page. Sits alongside ShareActions. Exports the structured classification +
// OCR + rationale for paste-into-issue / paste-into-script workflows. Pure
// clipboard API -- no new endpoints. Uses the app toast primitive for
// success / failure feedback instead of inline state.
//
// The format list + labels come from the shared EXPORT_FORMATS catalogue
// (lib/shot-export) so this single-shot surface and the /shots bulk surface
// (BulkExportButtons) can never expose a different set of formats (F86).

import { useCallback } from "react";
import {
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
  // Fallback for non-secure contexts (older Safari, http dev).
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

// Per-format presentation that's specific to the single-shot surface: the
// icon, the tooltip, and the dispatch to the matching serializer. The list /
// order / labels themselves live in the shared EXPORT_FORMATS catalogue.
const ICONS: Record<ExportFormatKey, React.ReactNode> = {
  json: <BracketsCurly size={14} weight="duotone" />,
  markdown: <MarkdownLogo size={14} weight="duotone" />,
  csv: <Table size={14} weight="duotone" />,
};

const TITLES: Record<ExportFormatKey, string> = {
  json: "Copy the structured fields as JSON",
  markdown: "Copy a Markdown summary for pasting into an issue",
  csv: "Copy one spreadsheet row (same columns as the bulk CSV export)",
};

function serialize(format: ExportFormatKey, shot: ShotExportInput): string {
  if (format === "json") return toJson(shot);
  if (format === "markdown") return toMarkdown(shot);
  return toCsv(shot);
}

export default function CopyExportButtons({ shot }: { shot: ShotExportInput }) {
  const copy = useCallback(
    async (format: ExportFormatKey, noun: string) => {
      try {
        await writeClipboard(serialize(format, shot));
        toast.success(`Copied shot as ${noun}.`);
      } catch {
        toast.error("Copy failed. Your browser blocked clipboard access.");
      }
    },
    [shot],
  );

  return (
    <div className="flex items-center gap-2">
      {EXPORT_FORMATS.map((f) => (
        <button
          key={f.key}
          type="button"
          onClick={() => copy(f.key, f.noun)}
          aria-label={`Copy shot as ${f.noun}`}
          title={TITLES[f.key]}
          className="num text-[11px] inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm border hover:bg-black/[0.03] focus:outline-none focus-visible:ring-2"
          style={{ borderColor: "var(--color-rule)" }}
        >
          {ICONS[f.key]} {f.noun}
        </button>
      ))}
    </div>
  );
}
