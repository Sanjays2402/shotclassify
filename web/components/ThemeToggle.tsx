"use client";

// Header theme toggle. Cycles Light -> Dim -> Auto on click; right-click /
// long-press exposes a tiny popover so a user can jump directly to any
// state. Persists to localStorage under STORAGE_KEY and tracks the
// prefers-color-scheme media query for Auto mode.
//
// The pre-paint init script (see lib/theme.ts) writes the correct
// data-theme attribute BEFORE React hydrates, so this component just
// needs to mirror the current value into local state and write through
// new selections.

import { useCallback, useEffect, useRef, useState } from "react";
import { Sun, Moon, Desktop } from "@phosphor-icons/react/dist/ssr";
import {
  labelForMode,
  nextMode,
  parseStoredMode,
  resolveTheme,
  STORAGE_KEY,
  type ThemeMode,
} from "@/lib/theme";

function readSystemDark(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export default function ThemeToggle() {
  // Default to "system" pre-mount; once hydrated we sync to the stored
  // value. Avoids a hydration mismatch -- the server can't know what the
  // browser has stashed.
  const [mode, setMode] = useState<ThemeMode>("system");
  const [systemDark, setSystemDark] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  // Read the persisted mode + current system pref on mount.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      setMode(parseStoredMode(raw));
    } catch {
      // Storage blocked -- stay on system default.
    }
    setSystemDark(readSystemDark());
  }, []);

  // Track the system preference so Auto mode flips when the user switches
  // their OS theme without reloading the page.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    if ("addEventListener" in mq) mq.addEventListener("change", onChange);
    else (mq as MediaQueryList).addListener(onChange);
    return () => {
      if ("removeEventListener" in mq) mq.removeEventListener("change", onChange);
      else (mq as MediaQueryList).removeListener(onChange);
    };
  }, []);

  // Apply the resolved theme to <html>.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const resolved = resolveTheme(mode, systemDark);
    document.documentElement.setAttribute("data-theme", resolved);
    document.documentElement.setAttribute("data-theme-mode", mode);
  }, [mode, systemDark]);

  // Click handler outside the popover closes it.
  useEffect(() => {
    if (!popoverOpen) return;
    function onDown(e: MouseEvent) {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setPopoverOpen(false);
      }
    }
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [popoverOpen]);

  const persist = useCallback((next: ThemeMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore quota / privacy-mode errors.
    }
  }, []);

  // Listen for the "T" hotkey from HotKeys.tsx -- cycles through modes
  // without duplicating persistence logic.
  useEffect(() => {
    function onCycle() {
      // Use the latest mode from state by reading via a setter callback.
      setMode((cur) => {
        const next = nextMode(cur);
        try {
          window.localStorage.setItem(STORAGE_KEY, next);
        } catch {
          /* ignore */
        }
        return next;
      });
    }
    window.addEventListener("shotclassify:theme-cycle", onCycle);
    return () =>
      window.removeEventListener("shotclassify:theme-cycle", onCycle);
  }, []);

  const onClick = () => persist(nextMode(mode));
  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setPopoverOpen((v) => !v);
  };

  const resolved = resolveTheme(mode, systemDark);

  const Icon =
    mode === "system" ? Desktop : resolved === "dim" ? Moon : Sun;

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={onClick}
        onContextMenu={onContextMenu}
        className="inline-flex items-center gap-1.5 px-2 py-1 rounded-sm border text-[11px] hover:bg-black/[0.04] transition-colors"
        style={{ borderColor: "var(--color-rule)" }}
        aria-label={`Theme: ${labelForMode(mode)} (click to cycle, right-click to choose)`}
        title={`Theme: ${labelForMode(mode)}${
          mode === "system" ? ` (currently ${resolved})` : ""
        }`}
      >
        <Icon size={14} weight="duotone" />
        <span className="eyebrow hidden lg:inline">{labelForMode(mode)}</span>
      </button>

      {popoverOpen && (
        <div
          role="menu"
          aria-label="Choose theme"
          className="absolute right-0 top-[110%] z-50 min-w-[120px] panel py-1"
          style={{ background: "#FFFEFA" }}
        >
          {(["light", "dim", "system"] as const).map((opt) => {
            const OptIcon =
              opt === "light" ? Sun : opt === "dim" ? Moon : Desktop;
            const active = mode === opt;
            return (
              <button
                key={opt}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                onClick={() => {
                  persist(opt);
                  setPopoverOpen(false);
                }}
                className="w-full text-left flex items-center gap-2 px-3 py-1.5 text-[12px] hover:bg-[color:var(--color-chalk-2)]"
                style={active ? { background: "var(--color-chalk-2)" } : undefined}
              >
                <OptIcon size={14} weight="duotone" />
                <span>{labelForMode(opt)}</span>
                {active && (
                  <span className="eyebrow ml-auto opacity-60">on</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
