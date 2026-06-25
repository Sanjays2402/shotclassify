"use client";

// StatInfoPopover: a small "?" affordance that sits in a /stats KPI card's
// header and opens a hover / focus popover explaining what the number means,
// how it's computed, and which window it covers (F34). Pure UI over the
// stat-explainers catalogue -- the parent passes the StatId and the active
// window length so this stays a thin renderer. Mirrors CategoryLegendChip:
// opens on mouse-enter AND keyboard focus so it's reachable without a
// pointer, closes on leave / blur / Escape, with a small close delay so the
// pointer can travel from the trigger into the popover.

import { useId, useRef, useState } from "react";
import { Info } from "@phosphor-icons/react/dist/ssr";
import { statExplainer, scopeNote, type StatId } from "@/lib/stat-explainers";

export function StatInfoPopover({
  stat,
  hours,
}: {
  stat: StatId;
  hours: number;
}) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const explainer = statExplainer(stat);

  const show = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setOpen(true);
  };
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
        className="inline-flex items-center justify-center w-4 h-4 rounded-full opacity-50 hover:opacity-90 transition-opacity"
        aria-expanded={open}
        aria-describedby={open ? popId : undefined}
        aria-label={`What is ${explainer.title}? ${explainer.definition}`}
      >
        <Info size={14} weight="duotone" />
      </button>

      {open && (
        <span
          id={popId}
          role="tooltip"
          className="absolute right-0 top-[calc(100%+6px)] z-50 panel p-3 w-[240px] flex flex-col gap-2 text-[11px] leading-relaxed shadow-lg"
          style={{ background: "#FFFEFA" }}
        >
          <span className="eyebrow">{explainer.title}</span>
          <span className="opacity-85">{explainer.definition}</span>
          <span className="opacity-70">{explainer.computed}</span>
          <span
            className="num text-[10px] opacity-60 pt-1 border-t"
            style={{ borderColor: "var(--color-rule)" }}
          >
            {scopeNote(explainer, hours)}
          </span>
        </span>
      )}
    </span>
  );
}

export default StatInfoPopover;
