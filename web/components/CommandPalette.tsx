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

import { fuzzyScore as _fuzzy, rankNav } from "@/lib/command-palette";

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

type Item = Nav | Hit;

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
  { kind: "nav", id: "nav-freeze", label: "Emergency freeze", hint: "Halt all writes during an incident", href: "/settings/security/freeze", icon: <Snowflake size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-notif", label: "Inbox", hint: "Notifications", href: "/notifications", icon: <Bell size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-usage", label: "Usage", hint: "Quota and history", href: "/usage", icon: <ChartBar size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-pricing", label: "Pricing", hint: "Plans", href: "/pricing", icon: <CreditCard size={16} weight="duotone" /> },
  { kind: "nav", id: "nav-account", label: "Account", hint: "Profile and data", href: "/account", icon: <UserCircle size={16} weight="duotone" /> },
];

export function fuzzyScore(q: string, label: string, hint: string): number {
  return _fuzzy(q, label, hint);
}

export default function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
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
      // focus the input after paint
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Debounced history search.
  useEffect(() => {
    if (!open) return;
    const Q = q.trim();
    if (!Q) {
      setHits([]);
      return;
    }
    let cancel = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const r = await fetch(
          `/api/history?q=${encodeURIComponent(Q)}&limit=8`,
          { credentials: "include" },
        );
        if (!r.ok) {
          if (!cancel) setHits([]);
          return;
        }
        const j = await r.json();
        const items: Hit[] = (j.items || j.history || []).map(
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
  }, [q, open]);

  const navMatches = useMemo<Nav[]>(() => {
    return rankNav(q, NAV, 8).slice(0, q.trim() ? 8 : 6);
  }, [q]);

  const items: Item[] = useMemo(() => [...navMatches, ...hits], [navMatches, hits]);

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

  const onKey = (e: React.KeyboardEvent) => {
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
            placeholder="Jump to a page or search your shots"
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
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => choose(n)}
                  >
                    <span className="opacity-80">{n.icon}</span>
                    <span className="flex-1 truncate">
                      <span className="font-medium">{n.label}</span>
                      <span className="opacity-60 ml-2 text-[12px]">{n.hint}</span>
                    </span>
                    <span className="opacity-50 text-[11px]">{n.href}</span>
                    <ArrowRight size={14} weight="duotone" className="opacity-50" />
                  </Row>
                );
              })}
            </Section>
          )}

          {hits.length > 0 && (
            <Section title={loading ? "Shots (loading...)" : "Shots"}>
              {hits.map((h, j) => {
                const i = navMatches.length + j;
                const active = cursor === i;
                const conf =
                  typeof h.confidence === "number"
                    ? `${Math.round(h.confidence * 100)}%`
                    : "";
                return (
                  <Row
                    key={`hit-${h.id}`}
                    active={active}
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
        </div>

        <div
          className="flex items-center justify-between px-3 py-2 text-[11px] border-t opacity-70"
          style={{ borderColor: "var(--color-rule, #e5e7eb)" }}
        >
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> navigate <Kbd>↵</Kbd> select
          </span>
          <span>
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd> to toggle
          </span>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="py-1">
      <div className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wider opacity-60">
        {title}
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
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
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
