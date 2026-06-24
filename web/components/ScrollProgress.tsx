"use client";

// ScrollProgress: a 3-pixel cue-yellow bar pinned to the top of the
// viewport that fills as the user scrolls. Pairs with a back-to-top
// circular FAB that fades in after the user has scrolled past a threshold.
//
// Both pieces are coalesced through requestAnimationFrame so the wheel /
// trackpad event firehose doesn't drive layout. Listeners are `passive`
// so we never block the compositor.

import { useEffect, useRef, useState } from "react";
import { ArrowUp } from "@phosphor-icons/react/dist/ssr";
import {
  backToTopVisible,
  scrollProgress,
} from "@/lib/scroll-progress";

type Props = {
  // Hide the FAB until the user has scrolled this many pixels. Defaults
  // to 600 -- about one hero band on most pages.
  fabThreshold?: number;
  // Height of the progress bar in pixels.
  barHeight?: number;
};

export default function ScrollProgress({
  fabThreshold = 600,
  barHeight = 3,
}: Props) {
  const [pct, setPct] = useState(0);
  const [showFab, setShowFab] = useState(false);
  // Track whether the user prefers reduced motion -- if so we skip the
  // smooth scroll and snap to top instead.
  const reduceMotion = useRef(false);
  const rafId = useRef<number | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      reduceMotion.current = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
    } catch {
      reduceMotion.current = false;
    }

    function read() {
      rafId.current = null;
      const doc = document.documentElement;
      const scrollTop =
        window.scrollY ?? doc.scrollTop ?? 0;
      const scrollHeight =
        doc.scrollHeight ?? document.body.scrollHeight ?? 0;
      const clientHeight = window.innerHeight ?? doc.clientHeight ?? 0;
      const next = scrollProgress(scrollTop, scrollHeight, clientHeight);
      setPct((prev) => {
        // Avoid extra renders when the rounded percent hasn't moved.
        const a = Math.round(prev * 1000);
        const b = Math.round(next * 1000);
        return a === b ? prev : next;
      });
      setShowFab((prev) => {
        const want = backToTopVisible(scrollTop, fabThreshold);
        return prev === want ? prev : want;
      });
    }

    function onScroll() {
      if (rafId.current != null) return;
      rafId.current = window.requestAnimationFrame(read);
    }

    function onResize() {
      // Resize can change the max scroll without firing scroll -- recompute.
      onScroll();
    }

    // Prime with the current state in case we hydrated mid-page.
    read();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize, { passive: true });

    return () => {
      if (rafId.current != null) cancelAnimationFrame(rafId.current);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
    };
  }, [fabThreshold]);

  const widthPct = `${(pct * 100).toFixed(2)}%`;

  function jumpToTop() {
    window.scrollTo({
      top: 0,
      behavior: reduceMotion.current ? "auto" : "smooth",
    });
  }

  return (
    <>
      <div
        role="progressbar"
        aria-label="Page scroll progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct * 100)}
        className="fixed top-0 left-0 right-0 z-[120] pointer-events-none"
        style={{
          height: barHeight,
          background: "transparent",
        }}
      >
        <span
          style={{
            display: "block",
            height: "100%",
            width: widthPct,
            background:
              "linear-gradient(90deg, var(--color-felt) 0%, var(--color-cue) 60%, var(--color-cue) 100%)",
            transition: "width 80ms linear",
            boxShadow: "0 0 8px rgba(245, 197, 24, 0.4)",
          }}
        />
      </div>

      <button
        type="button"
        onClick={jumpToTop}
        aria-label="Scroll to top"
        title="Back to top"
        className="fixed bottom-6 right-6 z-[115] rounded-full flex items-center justify-center transition-all duration-200"
        style={{
          width: 44,
          height: 44,
          background: "var(--color-ink)",
          color: "var(--color-cue)",
          border: "1px solid #000",
          boxShadow:
            "0 8px 24px -8px rgba(0,0,0,0.45), 0 2px 6px -1px rgba(0,0,0,0.30)",
          opacity: showFab ? 1 : 0,
          transform: showFab
            ? "translateY(0) scale(1)"
            : "translateY(8px) scale(0.9)",
          pointerEvents: showFab ? "auto" : "none",
        }}
      >
        <ArrowUp size={20} weight="bold" />
      </button>
    </>
  );
}
