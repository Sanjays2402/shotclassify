"use client";

// Global key bindings outside of CommandPalette (Cmd-K) and ShortcutsHelp (?).
// Single-key navigation (U / S / C) plus a "g t" sequence for scroll-to-top.
// Mirrors Linear's behaviour: bare-letter shortcuts only fire when no input
// is focused so typing in a search box never navigates away.

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { SHORTCUTS, createSequenceTracker } from "@/lib/shortcuts";

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

      // Then bare single-letter nav. Skip when any modifier is held so we
      // never collide with Cmd-S "save page" / Ctrl-U "view source".
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "u") {
        router.push("/upload");
      } else if (k === "s") {
        router.push("/shots");
      } else if (k === "c") {
        router.push("/calibration");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, tracker]);

  return null;
}
