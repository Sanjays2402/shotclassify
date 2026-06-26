"use client";

// A foldable subsection for the shot-detail right rail (F77). Wraps an
// existing rail panel (OCR / rationale / umpire / tags / frame) with a header
// that toggles its body open / closed. Collapsed state is owned by the parent
// page (so it can persist the whole rail at once via lib/detail-rail) and
// passed in -- this component is presentational.
//
// The fold uses a CSS grid-rows 1fr <-> 0fr transition, which animates to the
// content's natural height without measuring it in JS. globals.css drops the
// transition under prefers-reduced-motion so it snaps instead. The body stays
// in the DOM when collapsed (just clipped) so in-flight edits in the tag /
// umpire panels aren't unmounted mid-interaction.

import { CaretDown } from "@phosphor-icons/react/dist/ssr";
import type { ReactNode } from "react";

export function CollapsibleSection({
  title,
  collapsed,
  onToggle,
  children,
  dark = false,
  headerAccent,
}: {
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
  // Some rail panels use the dark "panel-dark" treatment (Rationale). Flip the
  // chrome colours so the header reads correctly on the dark backplate.
  dark?: boolean;
  // Optional colour for the eyebrow + caret (defaults to inherit / chalk).
  headerAccent?: string;
}) {
  const panelClass = dark ? "panel-dark" : "panel";
  const eyebrowStyle = headerAccent
    ? { color: headerAccent }
    : dark
      ? { color: "var(--color-chalk)" }
      : undefined;
  const bodyId = `rail-${title.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <div className={`${panelClass} p-5`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        aria-controls={bodyId}
        className="w-full flex items-center justify-between gap-2 text-left group"
      >
        <span className="eyebrow" style={eyebrowStyle}>
          {title}
        </span>
        <CaretDown
          size={14}
          weight="bold"
          aria-hidden
          className="shrink-0 opacity-60 group-hover:opacity-100 sc-rail-caret"
          style={{
            ...(eyebrowStyle ?? {}),
            transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)",
          }}
        />
      </button>
      <div
        id={bodyId}
        className="sc-rail-body"
        data-collapsed={collapsed ? "true" : "false"}
        // grid-rows fold: 1fr open, 0fr closed. The inner wrapper's overflow
        // hidden clips the content as the row collapses.
        style={{
          display: "grid",
          gridTemplateRows: collapsed ? "0fr" : "1fr",
        }}
      >
        <div className="overflow-hidden">
          {/* Spacer so the body doesn't kiss the header when expanded. */}
          <div className="pt-3">{children}</div>
        </div>
      </div>
    </div>
  );
}
