"use client";

// "Copy link to this comparison" button for the /compare page (this tick).
// The page advertised a "Shareable" view but only PRINTED a share path -- and
// that path ran the ids through shortId(), which truncates to 8 chars, so the
// displayed link was broken. This replaces it with a real clipboard button that
// copies the FULL ?a=ID&b=ID URL (via lib/compare-link), so a teammate can
// reopen the exact comparison. Mirrors CopyViewLinkButton's secure-context-
// aware clipboard write + app toast feedback.

import { useCallback } from "react";
import { LinkSimple } from "@phosphor-icons/react/dist/ssr";
import {
  buildCompareLink,
  canShareCompare,
  compareShareToastMessage,
} from "@/lib/compare-link";
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

export default function CopyCompareLinkButton({
  a,
  b,
}: {
  a: string;
  b: string;
}) {
  // Both sides required -- a one-sided link reopens an unfinished comparison,
  // so the button stays disabled until A and B are both picked.
  const ready = canShareCompare(a, b);

  const copy = useCallback(async () => {
    const base =
      typeof window !== "undefined" ? window.location.origin : "";
    const url = buildCompareLink(a, b, base);
    try {
      await writeClipboard(url);
      toast.success(compareShareToastMessage(a, b));
    } catch {
      toast.error("Copy failed. Your browser blocked clipboard access.");
    }
  }, [a, b]);

  return (
    <button
      type="button"
      onClick={copy}
      disabled={!ready}
      aria-label="Copy a shareable link to this comparison"
      title={
        ready
          ? "Copy a link that reopens this exact comparison"
          : "Pick both shots to share a link to the comparison"
      }
      className="btn btn-ghost text-[12px] inline-flex items-center gap-1.5"
    >
      <LinkSimple size={14} weight="duotone" /> Copy link
    </button>
  );
}
