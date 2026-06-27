"use client";

// Prev/next navigation through the recently-viewed shots ring on the shot-
// detail header (F49). Chevrons plus `[` / `]` keys step through the same MRU
// list the command palette surfaces, so paging back through what you were
// just reviewing is one keypress -- no fetch, no return to the list.
//
// Snapshot semantics: we read the ring ONCE on mount and freeze it. Because
// React fires child effects before parent effects, this component (a child of
// the detail page) captures the ring BEFORE the page's recordRecentShot()
// effect bumps the current shot to the front -- so the neighbours stay the
// ones the user actually browsed, not a list reordered out from under them.
// A shot reached by deep link (never previously viewed) isn't in the ring, so
// the nav hides itself rather than guessing.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CaretLeft, CaretRight } from "@phosphor-icons/react/dist/ssr";
import { readRecentShots, type RecentShot } from "@/lib/recent-shots";
import { neighborShots, hasShotNav, shotNavLabel } from "@/lib/shot-nav";

export default function ShotNav({ currentId }: { currentId: string }) {
  const router = useRouter();
  // Frozen pre-visit snapshot of the ring. Empty until mounted so SSR and the
  // first client render agree (no hydration mismatch); the effect fills it.
  const [ring, setRing] = useState<RecentShot[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setRing(readRecentShots());
    setMounted(true);
  }, []);

  const nav = neighborShots(ring, currentId);

  // `[` steps to the newer neighbour, `]` to the older one -- matching the
  // chevrons. Input-guarded and modifier-safe so typing in a field or hitting
  // a real Cmd/Ctrl chord never navigates. Re-bound when the targets change.
  useEffect(() => {
    if (!hasShotNav(nav)) return;
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      if (e.key === "[" && nav.prevId) {
        e.preventDefault();
        router.push(`/shots/${nav.prevId}`);
      } else if (e.key === "]" && nav.nextId) {
        e.preventDefault();
        router.push(`/shots/${nav.nextId}`);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav.prevId, nav.nextId, router]);

  // Nothing to render until we've read the ring, or when this shot isn't part
  // of a browsable trail.
  if (!mounted || !hasShotNav(nav)) return null;

  return (
    <div
      className="inline-flex items-center gap-1"
      role="group"
      aria-label="Recently viewed navigation"
    >
      <NavButton
        dir="prev"
        targetId={nav.prevId}
        neighborLabel={nav.prevLabel}
        onGo={(id) => router.push(`/shots/${id}`)}
      />
      <span
        className="num text-[10px] opacity-55 px-1 tabular-nums"
        title="Position in your recently-viewed shots"
      >
        {shotNavLabel(nav)}
      </span>
      {/* Tiny [ ] kbd hint so the keyboard step-through is discoverable
          without opening the ? overlay (F81). Hidden on very small screens to
          keep the header compact; the chevrons + their aria-labels still
          convey the keys there. aria-hidden because the buttons already spell
          out "( [ )" / "( ] )" for screen readers. */}
      <span
        className="hidden sm:inline-flex items-center gap-0.5 opacity-45"
        aria-hidden
        title="Use [ and ] to step through your recently-viewed shots"
      >
        <kbd className="kbd text-[9px] leading-none">[</kbd>
        <kbd className="kbd text-[9px] leading-none">]</kbd>
      </span>
      <NavButton
        dir="next"
        targetId={nav.nextId}
        neighborLabel={nav.nextLabel}
        onGo={(id) => router.push(`/shots/${id}`)}
      />
    </div>
  );
}

function NavButton({
  dir,
  targetId,
  neighborLabel,
  onGo,
}: {
  dir: "prev" | "next";
  targetId: string | null;
  neighborLabel: string | null;
  onGo: (id: string) => void;
}) {
  const disabled = !targetId;
  const Icon = dir === "prev" ? CaretLeft : CaretRight;
  // Spell out the neighbour so screen readers + hover get the destination, not
  // just a direction. Falls back to the generic wording when there's no label.
  const where = neighborLabel ? `: ${neighborLabel}` : "";
  const label =
    dir === "prev"
      ? `Newer shot you viewed ( [ )${where}`
      : `Older shot you viewed ( ] )${where}`;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => targetId && onGo(targetId)}
      aria-label={label}
      title={label}
      className="inline-flex items-center gap-1 h-7 px-1.5 rounded-sm border transition-colors disabled:opacity-30 disabled:cursor-not-allowed hover:bg-black/[0.05]"
      style={{ borderColor: "var(--color-rule)", color: "var(--color-ink)" }}
    >
      {dir === "prev" && <Icon size={14} weight="bold" />}
      {/* The on-screen neighbour label (F62) so the trail reads without a
          hover. Hidden on very small screens to keep the header tidy; the
          chevron + aria-label still convey the action there. */}
      {neighborLabel && (
        <span className="num text-[11px] max-w-[10rem] truncate hidden sm:inline">
          {neighborLabel}
        </span>
      )}
      {dir === "next" && <Icon size={14} weight="bold" />}
    </button>
  );
}
