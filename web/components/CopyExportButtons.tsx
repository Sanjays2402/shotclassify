"use client";

// Copy-as-JSON / copy-as-Markdown buttons for the shot detail page. Sits
// alongside ShareActions. Exports the structured classification + OCR +
// rationale for paste-into-issue / paste-into-script workflows. Pure
// clipboard API -- no new endpoints. Uses the app toast primitive for
// success / failure feedback instead of inline state.

import { useCallback } from "react";
import { BracketsCurly, MarkdownLogo } from "@phosphor-icons/react/dist/ssr";
import { toJson, toMarkdown, type ShotExportInput } from "@/lib/shot-export";
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

export default function CopyExportButtons({ shot }: { shot: ShotExportInput }) {
  const copy = useCallback(
    async (format: "json" | "markdown") => {
      const text = format === "json" ? toJson(shot) : toMarkdown(shot);
      try {
        await writeClipboard(text);
        toast.success(
          format === "json"
            ? "Copied shot as JSON."
            : "Copied shot as Markdown.",
        );
      } catch {
        toast.error("Copy failed. Your browser blocked clipboard access.");
      }
    },
    [shot],
  );

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => copy("json")}
        aria-label="Copy shot as JSON"
        title="Copy the structured fields as JSON"
        className="num text-[11px] inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm border hover:bg-black/[0.03] focus:outline-none focus-visible:ring-2"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <BracketsCurly size={14} weight="duotone" /> JSON
      </button>
      <button
        type="button"
        onClick={() => copy("markdown")}
        aria-label="Copy shot as Markdown"
        title="Copy a Markdown summary for pasting into an issue"
        className="num text-[11px] inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm border hover:bg-black/[0.03] focus:outline-none focus-visible:ring-2"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <MarkdownLogo size={14} weight="duotone" /> Markdown
      </button>
    </div>
  );
}
