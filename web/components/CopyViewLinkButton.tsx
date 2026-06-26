"use client";

// "Copy link to this view" button for the /shots list (F47). The inverse of
// the F30 deep-link parser: it serialises the page's CURRENT filter state
// back into the same query string the parser consumes, then copies an
// absolute URL to the clipboard so a teammate can open the exact filtered
// list. Pure clipboard API -- no new endpoints. Mirrors CopyExportButtons'
// secure-context-aware clipboard write + app toast feedback.

import { useCallback } from "react";
import { LinkSimple } from "@phosphor-icons/react/dist/ssr";
import {
  buildShotsDeepLink,
  buildShotsQuery,
  type ShotsFilterState,
} from "@/lib/shots-deeplink";
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

export default function CopyViewLinkButton({
  filters,
  disabled,
}: {
  filters: ShotsFilterState;
  disabled?: boolean;
}) {
  // Disable when the view is bare (no active filter) -- a link to the
  // unfiltered list is the same as the nav entry, so there's nothing to
  // share. Recomputed cheaply from the same builder the copy uses.
  const hasActiveFilter = buildShotsQuery(filters).length > 0;

  const copy = useCallback(async () => {
    const base =
      typeof window !== "undefined"
        ? `${window.location.origin}/shots`
        : "/shots";
    const url = buildShotsDeepLink(filters, base);
    try {
      await writeClipboard(url);
      toast.success("Copied a link to this filtered view.");
    } catch {
      toast.error("Copy failed. Your browser blocked clipboard access.");
    }
  }, [filters]);

  const off = disabled || !hasActiveFilter;

  return (
    <button
      type="button"
      onClick={copy}
      disabled={off}
      aria-label="Copy a shareable link to this filtered view"
      title={
        hasActiveFilter
          ? "Copy a link that reopens this exact filtered list"
          : "Apply a filter to share a link to it"
      }
      className="btn btn-ghost text-[12px] inline-flex items-center gap-1.5"
    >
      <LinkSimple size={14} weight="duotone" /> Copy link
    </button>
  );
}
