"use client";

// "What's new" — the header version pill that opens a changelog popover.
// Replaces the static `v0.1` label in the layout header. After a version
// bump the popover auto-opens once (a localStorage pointer remembers the
// newest version the user has acknowledged) and a cue-yellow dot marks the
// pill until they open it.

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkle, X } from "@phosphor-icons/react/dist/ssr";
import {
  CHANGELOG,
  CHANGELOG_STORAGE_KEY,
  currentVersion,
  hasUnseen,
  unseenCount,
  formatEntryDate,
} from "@/lib/changelog";

export default function WhatsNew() {
  const [open, setOpen] = useState(false);
  const [unseen, setUnseen] = useState(false);
  const [count, setCount] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const version = currentVersion();

  // On mount, read the seen-pointer and decide whether to nudge / auto-open.
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(CHANGELOG_STORAGE_KEY);
    } catch {
      stored = null;
    }
    const isUnseen = hasUnseen(stored);
    setUnseen(isUnseen);
    setCount(unseenCount(stored));
    // Auto-open once on a version bump, but NOT on a user's very first visit
    // (no pointer at all) -- a brand-new user is already being onboarded and
    // doesn't need a changelog in their face. Only nudge returning users.
    if (isUnseen && stored != null && stored !== "") {
      setOpen(true);
    }
  }, []);

  // Persist the current version as "seen" and clear the nudge.
  const acknowledge = useCallback(() => {
    try {
      localStorage.setItem(CHANGELOG_STORAGE_KEY, version);
    } catch {
      /* storage may be unavailable */
    }
    setUnseen(false);
    setCount(0);
  }, [version]);

  const toggle = useCallback(() => {
    setOpen((v) => {
      const next = !v;
      if (next) acknowledge();
      return next;
    });
  }, [acknowledge]);

  const close = useCallback(() => setOpen(false), []);

  // Dismiss on outside click / Escape while open.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        close();
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={toggle}
        className="eyebrow relative inline-flex items-center gap-1 hover:text-[color:var(--color-felt)] transition-colors"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={
          unseen
            ? `What's new in version ${version}, ${count} unread`
            : `What's new — version ${version}`
        }
        title="What's new"
        data-testid="whatsnew-pill"
      >
        v{version}
        {unseen && (
          <span
            className="absolute -top-1 -right-1.5 inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: "var(--color-cue)" }}
            aria-hidden
          />
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="What's new"
          className="panel absolute z-[110] mt-2 right-0 w-[340px] max-w-[88vw] shadow-2xl overflow-hidden"
          style={{ top: "100%" }}
          data-testid="whatsnew-popover"
        >
          <div
            className="flex items-center justify-between px-4 py-2.5 border-b"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <span className="eyebrow flex items-center gap-1.5">
              <Sparkle size={13} weight="duotone" /> What&apos;s new
            </span>
            <button
              type="button"
              onClick={close}
              aria-label="Close"
              className="inline-flex items-center justify-center w-6 h-6 rounded-sm opacity-60 hover:opacity-100"
            >
              <X size={13} weight="bold" />
            </button>
          </div>

          <div className="max-h-[60vh] overflow-y-auto">
            {CHANGELOG.map((entry, i) => (
              <div
                key={entry.version}
                className="px-4 py-3 border-b last:border-b-0"
                style={{ borderColor: "var(--color-rule)" }}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="h-display text-[14px]">
                    v{entry.version}
                    {i === 0 && (
                      <span
                        className="ml-2 num text-[9px] px-1.5 py-0.5 rounded-sm align-middle"
                        style={{
                          background: "var(--color-felt)",
                          color: "var(--color-chalk)",
                        }}
                      >
                        LATEST
                      </span>
                    )}
                  </span>
                  <span className="num text-[10px] opacity-60">
                    {formatEntryDate(entry.date)}
                  </span>
                </div>
                <div className="text-[12.5px] font-medium mt-1">
                  {entry.title}
                </div>
                <ul className="mt-1.5 flex flex-col gap-1">
                  {entry.highlights.map((h, j) => (
                    <li
                      key={j}
                      className="text-[12px] opacity-80 leading-snug pl-3 relative"
                    >
                      <span
                        className="absolute left-0 top-[7px] inline-block w-1 h-1 rounded-full"
                        style={{ background: "var(--color-cue-deep)" }}
                        aria-hidden
                      />
                      {h}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
