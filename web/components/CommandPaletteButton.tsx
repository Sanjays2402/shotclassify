"use client";

/**
 * Small "search ⌘K" button in the header that dispatches a global event
 * the CommandPalette listens for. Lets keyboard-shy users discover the
 * palette by clicking.
 */

import { useCallback, useEffect, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";

export default function CommandPaletteButton() {
  const [isMac, setIsMac] = useState(true);

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setIsMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent));
    }
  }, []);

  const open = useCallback(() => {
    // Simulate the keyboard shortcut so the existing handler runs.
    const ev = new KeyboardEvent("keydown", {
      key: "k",
      code: "KeyK",
      metaKey: true,
      ctrlKey: true,
      bubbles: true,
    });
    window.dispatchEvent(ev);
  }, []);

  return (
    <button
      type="button"
      onClick={open}
      aria-label="Open command palette"
      title="Search and navigate"
      className="hidden sm:flex items-center gap-2 rounded-md border px-2 py-1 text-[12px] hover:bg-[color:var(--color-rule)]/40 transition-colors"
      style={{ borderColor: "var(--color-rule)" }}
    >
      <MagnifyingGlass size={14} weight="duotone" />
      <span className="opacity-70">Search</span>
      <span className="ml-2 inline-flex items-center gap-0.5">
        <kbd
          className="text-[10px] px-1 py-px rounded border"
          style={{ borderColor: "var(--color-rule)" }}
        >
          {isMac ? "⌘" : "Ctrl"}
        </kbd>
        <kbd
          className="text-[10px] px-1 py-px rounded border"
          style={{ borderColor: "var(--color-rule)" }}
        >
          K
        </kbd>
      </span>
    </button>
  );
}
