"use client";

// Global keyboard-shortcuts help overlay. Opens on "?" (typed as shift+/)
// outside of text inputs, or programmatically by dispatching the custom
// "shotclassify:shortcuts-help" event on window. Modal styling matches the
// broadcast-graphic system in app/globals.css (chalk surface, felt-green
// accent, mono labels). Linear / Raycast-style: keyboard-first, no chrome.

import { useEffect, useState } from "react";
import { SHORTCUTS, isMac, renderKeys, type Shortcut } from "@/lib/shortcuts";

const OPEN_EVENT = "shotclassify:shortcuts-help";

export function openShortcutsHelp() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(OPEN_EVENT));
}

export default function ShortcutsHelp() {
  const [open, setOpen] = useState(false);
  const [platform, setPlatform] = useState<string>("");

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setPlatform(navigator.platform || "");
    }
  }, []);

  // Bind the global "?" listener. We deliberately mirror HotKeys' input-guard
  // -- don't fire while the user is typing into a field.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const inField =
        !!target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
        return;
      }
      if (inField) return;
      if (e.key === "?" || (e.shiftKey && e.key === "/")) {
        // Don't compete with the command palette's "/" trigger -- "?" already
        // requires shift on US layouts, so this branch only fires on shift+/.
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    function onCustom() {
      setOpen(true);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onCustom);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onCustom);
    };
  }, [open]);

  if (!open) return null;

  // Group by scope so the modal reads top-to-bottom: Global, then page-
  // specific buckets. Today the catalogue is all-global; the layout is
  // future-proof.
  const grouped: Record<string, Shortcut[]> = {};
  for (const s of SHORTCUTS) {
    grouped[s.scope] ??= [];
    grouped[s.scope].push(s);
  }
  const scopeOrder: Array<{ key: string; title: string }> = [
    { key: "global", title: "Anywhere" },
    { key: "shots", title: "On the shots list" },
    { key: "detail", title: "On a shot's detail" },
  ];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      className="fixed inset-0 z-[110] flex items-start justify-center px-4 pt-[10vh]"
      onClick={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
      style={{
        background: "rgba(10,15,12,0.55)",
        backdropFilter: "blur(3px)",
      }}
    >
      <div
        className="w-full max-w-2xl panel overflow-hidden"
        style={{
          // Slight pop above the chalk background.
          background: "#FFFEFA",
          boxShadow:
            "0 24px 60px -20px rgba(7, 48, 30, 0.45), 0 8px 18px -8px rgba(0,0,0,0.25)",
        }}
      >
        <header
          className="flex items-center gap-3 px-5 py-3 border-b"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <span
            className="inline-block w-2.5 h-2.5 rounded-full"
            style={{ background: "var(--color-felt)" }}
            aria-hidden
          />
          <div className="flex-1">
            <div className="eyebrow">Cheat sheet</div>
            <h2 className="h-display text-[20px] leading-none mt-0.5">
              Keyboard shortcuts
            </h2>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="btn btn-ghost text-[11px]"
            aria-label="Close shortcuts help"
          >
            Close <span className="kbd ml-1">Esc</span>
          </button>
        </header>

        <div className="px-5 py-4 max-h-[60vh] overflow-y-auto">
          {scopeOrder.map(({ key, title }) => {
            const items = grouped[key];
            if (!items || items.length === 0) return null;
            return (
              <section key={key} className="mb-5 last:mb-0">
                <div className="eyebrow mb-2">{title}</div>
                <ul className="flex flex-col gap-1">
                  {items.map((s) => {
                    const keys = renderKeys(s.combo, platform);
                    return (
                      <li
                        key={s.id}
                        className="grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-sm px-2 py-1.5 hover:bg-[color:var(--color-chalk-2)]"
                      >
                        <div className="flex items-center gap-1">
                          {keys.map((k, i) => (
                            <span key={i} className="flex items-center gap-1">
                              {i > 0 && s.combo.match.includes(" ") && (
                                <span className="eyebrow opacity-50">then</span>
                              )}
                              <kbd className="kbd">{k}</kbd>
                            </span>
                          ))}
                        </div>
                        <span className="text-[13px]">{s.label}</span>
                        {s.hint ? (
                          <span className="num text-[11px] opacity-60 whitespace-nowrap">
                            {s.hint}
                          </span>
                        ) : (
                          <span />
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>

        <footer
          className="px-5 py-2.5 border-t flex items-center justify-between text-[11px]"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <span className="eyebrow">
            {isMac(platform) ? "macOS layout" : "Windows / Linux layout"}
          </span>
          <span className="opacity-60">
            Press <span className="kbd">?</span> any time to reopen
          </span>
        </footer>
      </div>
    </div>
  );
}
