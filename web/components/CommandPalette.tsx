"use client";

/**
 * Global command palette. Opens with Cmd/Ctrl+K (or "/" outside inputs).
 * - Live-searches classification history (filename + OCR + tags + label)
 *   through /api/history?q=...
 * - Jumps to any major page in the app via fuzzy match.
 * - Keyboard-first: arrows to move, Enter to choose, Esc to close.
 *
 * Wired into the root layout so every page picks it up automatically.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  MagnifyingGlass,
  ArrowRight,
  Image as ImageIcon,
  Lightning,
  House,
  ChartBar,
  Upload,
  Files,
  Key,
  WebhooksLogo,
  Bell,
  CreditCard,
  UserCircle,
  Books,
  ChartLineUp,
  GitDiff,
  Sparkle,
  Gauge,
  Broadcast,
  ClockCounterClockwise,
  Snowflake,
} from "@phosphor-icons/react";

import { fuzzyScore as _fuzzy, rankNav, digitJumpIndex, paletteRestingHint, shotsScopeHints, shortLabelForHint, recentCountLabel, inboxCountLabel } from "@/lib/command-palette";
import { chordKeysForRoute } from "@/lib/goto-chords";
import { SHORTCUTS } from "@/lib/shortcuts";
import {
  parseFacets,
  hasFacets,
  facetsToHistoryParams,
  describeFacets,
} from "@/lib/palette-facets";
import { readRecentShots, clearRecentShots, type RecentShot } from "@/lib/recent-shots";
import { relativeTime } from "@/lib/relative-time";
import { ENDPOINTS } from "@/lib/api";

type Nav = {
  kind: "nav";
  id: string;
  label: string;
  hint: string;
  href: string;
  icon: React.ReactNode;
};

type Hit = {
  kind: "hit";
  id: string;
  filename: string;
  primary_category?: string;
  confidence?: number;
  created_at?: string;
  label?: string | null;
  tags?: string[];
};

type Recent = {
  kind: "recent";
  id: string;
  label: string;
  category?: string;
  // Epoch ms of the last visit, for the "viewed 3m ago" trailing hint (F59).
  viewedAt: number;
};

type Item = Nav | Hit | Recent;

const NAV: Nav[] = [
  { kind: "nav", id: "nav-live", label: "Live", hint: "Realtime classifier", href: "/", icon: <House size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-demo", label: "Demo", hint: "Interactive demo", href: "/demo", icon: <Sparkle size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-shots", label: "Shots", hint: "Browse history", href: "/shots", icon: <Files size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-upload", label: "Upload", hint: "Classify a new image", href: "/upload", icon: <Upload size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-batch", label: "Batch", hint: "Bulk classify a folder", href: "/batch", icon: <Files size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-stats", label: "Stats", hint: "Aggregate analytics", href: "/stats", icon: <ChartBar size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-compare", label: "Compare", hint: "Side by side", href: "/compare", icon: <GitDiff size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-calibration", label: "Calibration", hint: "Confidence calibration", href: "/calibration", icon: <ChartLineUp size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-keys", label: "API keys", hint: "Personal API keys", href: "/keys", icon: <Key size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-docs", label: "API docs", hint: "Endpoints and examples", href: "/api-docs", icon: <Books size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-webhooks", label: "Webhooks", hint: "Outbound delivery", href: "/webhooks", icon: <WebhooksLogo size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-rate-limits", label: "Rate limits", hint: "Per workspace and per key quotas", href: "/settings/security/rate-limits", icon: <Gauge size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-audit-sinks", label: "Audit sinks", hint: "Forward audit log to SIEM", href: "/settings/security/audit-sinks", icon: <Broadcast size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-audit-retention", label: "Audit retention", hint: "How long to keep audit rows", href: "/settings/security/audit-retention", icon: <ClockCounterClockwise size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-upload-content-types", label: "Upload content types", hint: "Allow-list MIME types accepted by classify", href: "/settings/security/upload-content-types", icon: <ImageIcon size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-freeze", label: "Emergency freeze", hint: "Halt all writes during an incident", href: "/settings/security/freeze", icon: <Snowflake size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-notif", label: "Inbox", hint: "Notifications", href: "/notifications", icon: <Bell size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-usage", label: "Usage", hint: "Quota and history", href: "/usage", icon: <ChartBar size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-pricing", label: "Pricing", hint: "Plans", href: "/pricing", icon: <CreditCard size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-account", label: "Account", hint: "Profile and data", href: "/account", icon: <UserCircle size={16} weight="duotone" /> },
];

export function fuzzyScore(q: string, label: string, hint: string): number {
  return _fuzzy(q, label, hint);
}

// Shots-list shortcut legend (F70), derived once from the frozen catalogue.
// Surfaced in the palette footer so the `v` / `d` single-letter shortcuts are
// discoverable from anywhere, not just the `?` overlay.
const SHOTS_HINTS = shotsScopeHints(SHORTCUTS);

export default function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [recents, setRecents] = useState<Recent[]>([]);
  // Reference instant for the recents' "viewed Nm ago" hints (F59), captured
  // when the palette opens so every row measures against the same now and the
  // labels don't drift mid-session.
  const [recentsNow, setRecentsNow] = useState(0);
  // Unread notification count for the Inbox nav-row badge (F95). Fetched fresh
  // each time the palette opens so it reflects activity since the last open.
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Open/close via Cmd/Ctrl+K or "/" outside inputs.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      const inField =
        !!t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          (t as HTMLElement).isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (e.key === "/" && !inField && !open) {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Reset when opened.
  useEffect(() => {
    if (open) {
      setQ("");
      setHits([]);
      setCursor(0);
      // Pull the recently-viewed ring fresh each open so a shot visited in
      // another tab shows up. Mapped to the palette's `recent` item shape.
      setRecentsNow(Date.now());
      setRecents(
        readRecentShots().map((r: RecentShot) => ({
          kind: "recent" as const,
          id: r.id,
          label: r.label,
          category: r.category,
          viewedAt: r.viewedAt,
        })),
      );
      // focus the input after paint
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Pull the unread notification count when the palette opens, for the Inbox
  // row badge (F95). Best-effort: a failed / unauthenticated fetch silently
  // leaves the badge hidden (count stays 0). Cancelled if the palette closes
  // before the response lands.
  useEffect(() => {
    if (!open) return;
    let cancel = false;
    (async () => {
      try {
        const r = await fetch("/api/notifications?limit=1", {
          credentials: "same-origin",
        });
        if (!r.ok) return;
        const j = await r.json();
        const n = Number(j?.unread);
        if (!cancel) setUnread(Number.isFinite(n) ? n : 0);
      } catch {
        /* leave the badge hidden on any error */
      }
    })();
    return () => {
      cancel = true;
    };
  }, [open]);

  // Parse inline facets (`class:receipt`, `>90%`, `tag:foo`) out of the
  // query. The residual free text drives the fuzzy nav + history search.
  const facets = useMemo(() => parseFacets(q), [q]);
  const facetSummary = describeFacets(facets);

  // Debounced history search.
  useEffect(() => {
    if (!open) return;
    // Search when there's residual text OR at least one structured facet --
    // `class:receipt` alone should list receipts even with no free text.
    const Q = facets.text.trim();
    if (!Q && !hasFacets(facets)) {
      setHits([]);
      return;
    }
    let cancel = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const url = ENDPOINTS.history(facetsToHistoryParams(facets, 8));
        const r = await fetch(url, { credentials: "include" });
        if (!r.ok) {
          if (!cancel) setHits([]);
          return;
        }
        const j = await r.json();
        const raw = Array.isArray(j) ? j : j.items || j.history || j.data || [];
        const items: Hit[] = (raw as Record<string, unknown>[]).map(
          (x: Record<string, unknown>) => ({
            kind: "hit" as const,
            id: String(x.id ?? ""),
            filename: String(x.filename ?? x.label ?? "shot"),
            primary_category: x.primary_category as string | undefined,
            confidence: x.confidence as number | undefined,
            created_at: x.created_at as string | undefined,
            label: (x.label as string | null) ?? null,
            tags: (x.tags as string[] | undefined) ?? [],
          }),
        );
        if (!cancel) setHits(items.filter((h) => h.id));
      } catch {
        if (!cancel) setHits([]);
      } finally {
        if (!cancel) setLoading(false);
      }
    }, 180);
    return () => {
      cancel = true;
      clearTimeout(t);
    };
  }, [facets, open]);

  const navMatches = useMemo<Nav[]>(() => {
    return rankNav(q, NAV, 8).slice(0, q.trim() ? 8 : 6);
  }, [q]);

  // Show the recently-viewed ring only on the resting palette -- no free
  // text and no structured facet. Once the user starts typing, live search
  // hits take over the lower section.
  const showRecents = !facets.text.trim() && !hasFacets(facets);
  const recentItems = useMemo<Recent[]>(
    () => (showRecents ? recents : []),
    [showRecents, recents],
  );

  // Resting-palette discoverability hint (F50): on a bare palette with no
  // query AND an empty recents ring, the lower half is just nav -- nothing
  // tells a new user that opening a shot will seed a one-keystroke "Recently
  // viewed" shortcut. Show a one-line tip in exactly that state; it steps
  // aside the moment they type or once they've viewed a shot.
  const restingHint = paletteRestingHint(showRecents, recents.length);

  const items: Item[] = useMemo(
    () => [...navMatches, ...recentItems, ...hits],
    [navMatches, recentItems, hits],
  );

  // Clamp cursor.
  useEffect(() => {
    setCursor((c) => Math.min(c, Math.max(0, items.length - 1)));
  }, [items.length]);

  const choose = useCallback(
    (it: Item) => {
      setOpen(false);
      if (it.kind === "nav") router.push(it.href);
      else router.push(`/shots/${encodeURIComponent(it.id)}`);
    },
    [router],
  );

  // Wipe the recently-viewed ring (F42) and drop the local list so the
  // section disappears immediately, without closing the palette. Stops the
  // click from bubbling to a row. Keyboard cursor falls back into range via
  // the existing clamp effect once `recents` empties.
  const clearRecents = useCallback(() => {
    clearRecentShots();
    setRecents([]);
    setCursor(0);
  }, []);

  const onKey = (e: React.KeyboardEvent) => {
    // Cmd/Ctrl + 1-9 jumps straight to (and opens) the Nth flat result --
    // nav, then recents, then hits, the same order shown. Out-of-range
    // digits and 0 no-op so the browser keeps its native chord (e.g. Cmd+0
    // zoom-reset). (F45)
    if (e.metaKey || e.ctrlKey) {
      const idx = digitJumpIndex(e.key, items.length);
      if (idx !== null) {
        e.preventDefault();
        setCursor(idx);
        choose(items[idx]);
        return;
      }
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(items.length - 1, c + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const it = items[cursor];
      if (it) choose(it);
    }
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      className="fixed inset-0 z-[100] flex items-start justify-center px-4 pt-[12vh]"
      onClick={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
      style={{ background: "rgba(10,15,12,0.45)", backdropFilter: "blur(2px)" }}
    >
      <div
        className="w-full max-w-xl rounded-xl border shadow-2xl overflow-hidden"
        style={{
          background: "var(--color-chalk, #fff)",
          borderColor: "var(--color-rule, #e5e7eb)",
        }}
      >
        <div
          className="flex items-center gap-2 px-3 py-2.5 border-b"
          style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
        >
          <MagnifyingGlass size={18} weight="duotone" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder="Jump to a page, or search shots — try class:receipt >90%"
            aria-label="Search command palette"
            className="flex-1 bg-transparent outline-none text-[14px]"
          />
          <kbd
            className="text-[10px] px-1.5 py-0.5 rounded border opacity-70"
            style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
          >
            Esc
          </kbd>
        </div>

        {facetSummary && (
          <div
            className="flex items-center gap-2 px-3 py-1.5 border-b text-[11px]"
            style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
            data-testid="palette-facets"
          >
            <span className="opacity-60 uppercase tracking-wider text-[10px]">
              Filtering
            </span>
            <span
              className="num inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm"
              style={{
                background: "var(--color-felt, #1f4d2b)",
                color: "var(--color-chalk, #fff)",
              }}
            >
              {facetSummary}
            </span>
            {facets.text && (
              <span className="opacity-60">
                matching &ldquo;{facets.text}&rdquo;
              </span>
            )}
          </div>
        )}

        <div
          ref={listRef}
          className="max-h-[55vh] overflow-y-auto"
          role="listbox"
          aria-label="Results"
        >
          {items.length === 0 && (
            <div className="px-4 py-8 text-center text-[13px] opacity-70">
              {loading ? "Searching..." : "No matches. Try a filename, an OCR snippet, or a page name."}
            </div>
          )}

          {navMatches.length > 0 && (
            <Section title="Jump to">
              {navMatches.map((n, idx) => {
                const i = idx;
                const active = cursor === i;
                return (
                  <Row
                    key={n.id}
                    active={active}
                    jump={i < 9 ? i + 1 : undefined}
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => choose(n)}
                  >
                    <span className="opacity-80">{n.icon}</span>
                    <span className="flex-1 truncate">
                      <span className="font-medium">{n.label}</span>
                      <span className="opacity-60 ml-2 text-[12px]">{n.hint}</span>
                      {/* Faint "N recent" badge on the Shots row (F83) so the
                          user knows the recently-viewed trail has entries
                          before they scroll down to the (query-empty-only)
                          Recently viewed section. */}
                      {(() => {
                        const badge = recentCountLabel(n.href, recents.length);
                        return badge ? (
                          <span
                            className="num ml-2 text-[10px] px-1.5 py-0.5 rounded-sm align-middle opacity-70"
                            style={{
                              background: "var(--color-chalk-2, #f3f3ee)",
                              border: "1px solid var(--color-rule, #e5e7eb)",
                            }}
                            title={`${recents.length} recently-viewed shot${recents.length === 1 ? "" : "s"}`}
                          >
                            {badge}
                          </span>
                        ) : null;
                      })()}
                      {/* Faint "N unread" badge on the Inbox row (F95), mirroring
                          the Shots recents badge, so pending notifications are
                          visible straight from the palette. Felt-green to read
                          as an active signal, not just a count. */}
                      {(() => {
                        const badge = inboxCountLabel(n.href, unread);
                        return badge ? (
                          <span
                            className="num ml-2 text-[10px] px-1.5 py-0.5 rounded-sm align-middle"
                            style={{
                              background: "var(--color-felt, #1f4d2b)",
                              color: "var(--color-chalk, #fff)",
                            }}
                            title={`${unread} unread notification${unread === 1 ? "" : "s"}`}
                          >
                            {badge}
                          </span>
                        ) : null;
                      })()}
                    </span>
                    {(() => {
                      // Surface the Linear-style `g <x>` section chord for any
                      // nav row that has one (F68), so the shortcut is
                      // discoverable straight from the palette -- no cheat
                      // sheet needed. Rows without a chord keep showing their
                      // route. GOTO_CHORDS stays the single source of truth.
                      const chord = chordKeysForRoute(n.href);
                      if (chord) {
                        return (
                          <span
                            className="hidden sm:inline-flex items-center gap-0.5"
                            aria-label={`Shortcut: press ${chord[0]} then ${chord[1]}`}
                            title={`Press ${chord[0]} then ${chord[1]}`}
                          >
                            <kbd className="kbd text-[10px]">{chord[0]}</kbd>
                            <kbd className="kbd text-[10px]">{chord[1]}</kbd>
                          </span>
                        );
                      }
                      return (
                        <span className="opacity-50 text-[11px]">{n.href}</span>
                      );
                    })()}
                    <ArrowRight size={14} weight="duotone" className="opacity-50" />
                  </Row>
                );
              })}
            </Section>
          )}

          {recentItems.length > 0 && (
            <Section
              title="Recently viewed"
              action={
                <button
                  type="button"
                  // Don't let the click bubble to a Row / steal palette focus.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={(e) => {
                    e.stopPropagation();
                    clearRecents();
                  }}
                  className="text-[10px] uppercase tracking-wider opacity-60 hover:opacity-100 transition-opacity"
                  aria-label="Clear recently viewed shots"
                  title="Clear the recently-viewed list"
                >
                  Clear
                </button>
              }
            >
              {recentItems.map((r, k) => {
                const i = navMatches.length + k;
                const active = cursor === i;
                return (
                  <Row
                    key={`recent-${r.id}`}
                    active={active}
                    jump={i < 9 ? i + 1 : undefined}
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => choose(r)}
                  >
                    <ClockCounterClockwise
                      size={16}
                      weight="duotone"
                      className="opacity-80"
                    />
                    <span className="flex-1 truncate">
                      <span className="font-medium truncate">{r.label}</span>
                      {r.category && (
                        <span className="opacity-60 ml-2 text-[12px] uppercase tracking-wide">
                          {r.category}
                        </span>
                      )}
                    </span>
                    {recentsNow > 0 && relativeTime(r.viewedAt, recentsNow) && (
                      <span
                        className="opacity-50 text-[11px] whitespace-nowrap"
                        title={
                          Number.isFinite(r.viewedAt)
                            ? new Date(r.viewedAt).toLocaleString()
                            : undefined
                        }
                      >
                        {relativeTime(r.viewedAt, recentsNow)}
                      </span>
                    )}
                    <ArrowRight size={14} weight="duotone" className="opacity-50" />
                  </Row>
                );
              })}
            </Section>
          )}

          {hits.length > 0 && (
            <Section title={loading ? "Shots (loading...)" : "Shots"}>
              {hits.map((h, j) => {
                const i = navMatches.length + recentItems.length + j;
                const active = cursor === i;
                const conf =
                  typeof h.confidence === "number"
                    ? `${Math.round(h.confidence * 100)}%`
                    : "";
                return (
                  <Row
                    key={`hit-${h.id}`}
                    active={active}
                    jump={i < 9 ? i + 1 : undefined}
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => choose(h)}
                  >
                    <ImageIcon size={16} weight="duotone" className="opacity-80" />
                    <span className="flex-1 truncate">
                      <span className="font-medium truncate">
                        {h.label || h.filename}
                      </span>
                      {h.primary_category && (
                        <span className="opacity-60 ml-2 text-[12px] uppercase tracking-wide">
                          {h.primary_category}
                        </span>
                      )}
                    </span>
                    {conf && (
                      <span className="opacity-60 text-[11px]">{conf}</span>
                    )}
                    <Lightning size={12} weight="duotone" className="opacity-50" />
                  </Row>
                );
              })}
            </Section>
          )}

          {restingHint && (
            <div
              className="px-3 pt-2 pb-3 text-[11px] flex items-center gap-1.5 opacity-55"
              data-testid="palette-resting-hint"
            >
              <Sparkle size={12} weight="duotone" className="shrink-0" />
              <span>{restingHint}</span>
            </div>
          )}
        </div>

        <div
          className="flex items-center justify-between px-3 py-2 text-[11px] border-t opacity-70"
          style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
        >
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> navigate <Kbd>↵</Kbd> select{" "}
            <Kbd>⌘</Kbd>
            <Kbd>1-9</Kbd> jump
          </span>
          <span>
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd> to toggle
          </span>
        </div>

        {SHOTS_HINTS.length > 0 && (
          <div
            className="flex items-center gap-3 px-3 py-1.5 text-[11px] border-t opacity-60 overflow-x-auto"
            style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
            data-testid="palette-shots-legend"
          >
            <span className="uppercase tracking-wider text-[10px] opacity-80 whitespace-nowrap">
              Shots list
            </span>
            {SHOTS_HINTS.map((h) => (
              <span
                key={h.id}
                className="inline-flex items-center gap-1 whitespace-nowrap"
                title={h.label}
              >
                {h.keys.map((k, i) => (
                  <Kbd key={i}>{k}</Kbd>
                ))}
                <span className="opacity-80">{shortLabelForHint(h.label)}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="py-1">
      <div className="px-3 pt-2 pb-1 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider opacity-60">
          {title}
        </span>
        {action}
      </div>
      {children}
    </div>
  );
}

function Row({
  children,
  active,
  onClick,
  onMouseEnter,
  jump,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
  // 1-9 for the first nine rows -- rendered as a faint trailing hint so the
  // Cmd+digit quick-jump (F45) is discoverable. Hidden on the active row to
  // keep the selection chrome clean.
  jump?: number;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      className="w-full text-left flex items-center gap-2.5 px-3 py-2 text-[13px]"
      style={{
        background: active ? "var(--color-felt, #1f4d2b)" : "transparent",
        color: active ? "var(--color-chalk, #fff)" : "inherit",
      }}
    >
      {children}
      {jump != null && !active && (
        <kbd
          className="hidden sm:inline-block text-[9px] leading-none px-1 py-0.5 rounded border opacity-40 ml-1"
          style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
          aria-hidden
        >
          ⌘{jump}
        </kbd>
      )}
    </button>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd
      className="text-[10px] px-1.5 py-0.5 rounded border mx-0.5"
      style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
    >
      {children}
    </kbd>
  );
}
