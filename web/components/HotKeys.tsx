"use client";

// Global key bindings outside of CommandPalette (Cmd-K) and ShortcutsHelp (?).
// Single-key navigation (U / S / C / T) plus a "g t" sequence for
// scroll-to-top. Mirrors Linear's behaviour: bare-letter shortcuts only fire
// when no input is focused so typing in a search box never navigates away.

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { SHORTCUTS, createSequenceTracker } from "@/lib/shortcuts";
import { routeForChord } from "@/lib/goto-chords";

export default function HotKeys() {
  const router = useRouter();
  // The sequence tracker is stable across re-renders so partial sequences
  // survive component re-mounts; useMemo with an empty dep array is fine
  // because SHORTCUTS is module-frozen.
  const tracker = useMemo(() => createSequenceTracker(SHORTCUTS), []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      // First, feed the sequence tracker -- this handles "g t" -> scroll up.
      const seq = tracker.feed(
        {
          key: e.key,
          metaKey: e.metaKey,
          ctrlKey: e.ctrlKey,
          altKey: e.altKey,
          shiftKey: e.shiftKey,
        },
        performance.now(),
      );
      if (seq === "g t") {
        e.preventDefault();
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      // Linear-style section jumps: `g s` -> /stats, `g h` -> /shots, etc.
      // Resolved before the bare single-letter switch so a completed chord
      // wins over the legacy fast-path letters.
      const chordRoute = routeForChord(seq);
      if (chordRoute) {
        e.preventDefault();
        router.push(chordRoute);
        return;
      }

      // Then bare single-letter nav. Skip when any modifier is held so we
      // never collide with Cmd-S "save page" / Ctrl-U "view source", and so
      // Shift-letter chords owned by a page (e.g. the shot-detail rail's
      // Shift+E / Shift+C expand/collapse, F93) don't ALSO navigate. This
      // matches matchesShortcut's bare-combo rule, which rejects an
      // unrequested shift.
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      const k = e.key.toLowerCase();
      if (k === "u") {
        router.push("/upload");
      } else if (k === "s") {
        router.push("/shots");
      } else if (k === "c") {
        router.push("/calibration");
      } else if (k === "t") {
        // Cycle theme via the ThemeToggle component's event listener so
        // the binding here doesn't need to duplicate persistence logic.
        window.dispatchEvent(new Event("shotclassify:theme-cycle"));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, tracker]);

  return null;
}
