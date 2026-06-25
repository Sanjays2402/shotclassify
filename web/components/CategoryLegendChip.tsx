"use client";

// CategoryLegendChip: wraps a <Chip> with a hover / focus popover showing
// the class's count, share of the window, mean confidence, and a "view in
// shots" deep link (F14). Pure UI over the stats aggregate's per_class
// data -- the parent passes a pre-built summary so this stays a renderer.
// The popover opens on mouse-enter AND keyboard focus so it's reachable
// without a pointer, and closes on leave / blur / Escape.

import { useId, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import type { CategoryLegendSummary } from "@/lib/category-legend";

export function CategoryLegendChip({ summary }: { summary: CategoryLegendSummary }) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setOpen(true);
  };
  // Small close delay so moving the pointer from the chip into the popover
  // (to click the link) doesn't dismiss it.
  const hide = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 120);
  };

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocusCapture={show}
      onBlurCapture={hide}
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <button
        type="button"
        className="inline-flex rounded-sm"
        aria-expanded={open}
        aria-describedby={open ? popId : undefined}
        aria-label={`${summary.label}: ${summary.count} shots, ${summary.sharePct} of window, mean confidence ${summary.meanConfidencePct}`}
      >
        <Chip cat={summary.category} />
      </button>

      {open && (
        <span
          id={popId}
          role="tooltip"
          className="absolute left-0 top-[calc(100%+6px)] z-50 panel p-3 w-[200px] flex flex-col gap-2 shadow-lg"
          style={{ background: "#FFFEFA" }}
        >
          <span className="eyebrow">{summary.label}</span>
          <span className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
            <span className="opacity-60">Count</span>
            <span className="num text-right">{summary.count.toLocaleString()}</span>
            <span className="opacity-60">Share</span>
            <span className="num text-right">{summary.sharePct}</span>
            <span className="opacity-60">Mean conf</span>
            <span className="num text-right">{summary.meanConfidencePct}</span>
          </span>
          <span
            className="h-1 rounded-sm overflow-hidden"
            style={{ background: "rgba(11,15,12,0.08)" }}
            aria-hidden
          >
            <span
              className="block h-full"
              style={{
                width: `${Math.min(100, summary.share * 100)}%`,
                background: `var(--color-cat-${summary.category.split("_")[0]})`,
              }}
            />
          </span>
          <Link
            href={summary.shotsHref}
            className="eyebrow flex items-center gap-1 opacity-80 hover:opacity-100 hover:underline"
          >
            View in shots <ArrowRight size={11} weight="bold" />
          </Link>
        </span>
      )}
    </span>
  );
}

export default CategoryLegendChip;
