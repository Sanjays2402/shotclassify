"use client";

// Header button that opens the keyboard-shortcuts help overlay. Mirrors the
// CommandPaletteButton pattern -- a tiny iconograhic cue so the discoverable
// "?" shortcut is also discoverable for mouse users. Dispatches the custom
// event the overlay listens for; no React context plumbing required.

import { Keyboard } from "@phosphor-icons/react/dist/ssr";
import { openShortcutsHelp } from "./ShortcutsHelp";

export default function ShortcutsHelpButton() {
  return (
    <button
      type="button"
      onClick={() => openShortcutsHelp()}
      className="hidden md:inline-flex items-center gap-1.5 px-2 py-1 rounded-sm border text-[11px] hover:bg-black/[0.04] transition-colors"
      style={{ borderColor: "var(--color-rule)" }}
      aria-label="Show keyboard shortcuts"
      title="Keyboard shortcuts (?)"
    >
      <Keyboard size={14} weight="duotone" />
      <span className="eyebrow">Shortcuts</span>
      <span className="kbd">?</span>
    </button>
  );
}
