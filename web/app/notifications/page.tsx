"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Bell,
  BellSlash,
  CheckCircle,
  Warning,
  Info,
  Trash,
  Check,
  ArrowSquareOut,
  MagnifyingGlass,
  X,
  CircleNotch,
  Funnel,
} from "@phosphor-icons/react/dist/ssr";
import { NotificationPrefsCard } from "@/components/NotificationPrefsCard";

type Notif = {
  id: string;
  kind: string;
  title: string;
  body: string;
  href: string | null;
  created_at: string;
  read_at: string | null;
};

type Page = {
  items: Notif[];
  total: number;
  matched: number;
  unread: number;
  next_cursor: number | null;
  filter: { q: string; kind: string; unread_only: boolean };
};

const KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All kinds" },
  { value: "classify.completed", label: "Classifications" },
  { value: "webhook.failed", label: "Webhook failures" },
  { value: "system", label: "System" },
];

const PAGE_SIZE = 25;

function fmt(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function kindIcon(kind: string) {
  if (kind === "classify.completed")
    return (
      <CheckCircle
        size={18}
        weight="duotone"
        style={{ color: "var(--color-felt)" }}
      />
    );
  if (kind === "webhook.failed")
    return (
      <Warning size={18} weight="duotone" style={{ color: "#b45309" }} />
    );
  return <Info size={18} weight="duotone" />;
}

function Skeleton() {
  return (
    <div className="animate-pulse">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="px-4 py-3 border-b"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div
            className="h-3 w-1/3 rounded mb-2"
            style={{ background: "var(--color-rule)" }}
          />
          <div
            className="h-2 w-2/3 rounded"
            style={{ background: "var(--color-rule)" }}
          />
        </div>
      ))}
    </div>
  );
}

function useDebounce<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function NotificationsPage() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const [unreadOnly, setUnreadOnly] = useState(false);

  const qDebounced = useDebounce(q.trim(), 250);

  const [items, setItems] = useState<Notif[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [cursor, setCursor] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildUrl = useCallback(
    (atCursor: number) => {
      const sp = new URLSearchParams();
      sp.set("paged", "1");
      sp.set("limit", String(PAGE_SIZE));
      sp.set("cursor", String(atCursor));
      if (qDebounced) sp.set("q", qDebounced);
      if (kind && kind !== "all") sp.set("kind", kind);
      if (unreadOnly) sp.set("unread_only", "1");
      return `/api/notifications?${sp.toString()}`;
    },
    [qDebounced, kind, unreadOnly],
  );

  const load = useCallback(
    async (atCursor: number, append: boolean) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      try {
        const res = await fetch(buildUrl(atCursor), { cache: "no-store" });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const j = (await res.json()) as Page;
        setPage(j);
        setItems((prev) => (append ? [...prev, ...j.items] : j.items));
        setCursor(atCursor);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load.");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [buildUrl],
  );

  // Reload from the top whenever filters change.
  useEffect(() => {
    load(0, false);
  }, [load]);

  // Background refresh every 20s, but only for the first page.
  useEffect(() => {
    const id = setInterval(() => {
      if (cursor === 0 && !busy) load(0, false);
    }, 20_000);
    return () => clearInterval(id);
  }, [cursor, busy, load]);

  const reload = () => load(0, false);
  const loadMore = () => {
    if (page?.next_cursor != null) load(page.next_cursor, true);
  };

  const markRead = async (id: string) => {
    setBusy(true);
    await fetch(`/api/notifications/${id}`, { method: "PATCH" });
    await reload();
    setBusy(false);
  };
  const remove = async (id: string) => {
    setBusy(true);
    await fetch(`/api/notifications/${id}`, { method: "DELETE" });
    await reload();
    setBusy(false);
  };
  const markAllRead = async () => {
    setBusy(true);
    await fetch("/api/notifications", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "mark_all_read" }),
    });
    await reload();
    setBusy(false);
  };
  const clearAll = async () => {
    if (!confirm("Clear every notification? This cannot be undone.")) return;
    setBusy(true);
    await fetch("/api/notifications", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "clear" }),
    });
    await reload();
    setBusy(false);
  };

  const unread = page?.unread ?? 0;
  const matched = page?.matched ?? 0;
  const total = page?.total ?? 0;

  const filtersActive = useMemo(
    () => Boolean(qDebounced) || kind !== "all" || unreadOnly,
    [qDebounced, kind, unreadOnly],
  );

  const clearFilters = () => {
    setQ("");
    setKind("all");
    setUnreadOnly(false);
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-start justify-between gap-4 mb-5 flex-wrap">
        <div>
          <h1 className="h-display text-[26px] tracking-tight flex items-center gap-2">
            <Bell size={22} weight="duotone" />
            Notifications
          </h1>
          <p className="text-[13px] opacity-70 mt-1">
            Activity from classifications, webhooks, and the system.
            {unread > 0 ? ` ${unread} unread.` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={markAllRead}
            disabled={busy || unread === 0}
            className="inline-flex items-center gap-1 text-[12px] px-2.5 py-1.5 rounded-md border disabled:opacity-40"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <Check size={14} weight="duotone" /> Mark all read
          </button>
          <button
            onClick={clearAll}
            disabled={busy || total === 0}
            className="inline-flex items-center gap-1 text-[12px] px-2.5 py-1.5 rounded-md border disabled:opacity-40"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <Trash size={14} weight="duotone" /> Clear all
          </button>
        </div>
      </div>

      <div
        className="rounded-md border p-3 mb-3 flex flex-col sm:flex-row gap-2 sm:items-center"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <div className="relative flex-1 min-w-0">
          <MagnifyingGlass
            size={14}
            weight="bold"
            className="absolute left-2.5 top-1/2 -translate-y-1/2 opacity-60"
          />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search title, body, or kind"
            aria-label="Search notifications"
            className="w-full rounded-md border pl-8 pr-8 py-2 text-[13px] bg-white outline-none focus:ring-2"
            style={{ borderColor: "var(--color-rule)" }}
          />
          {q && (
            <button
              type="button"
              onClick={() => setQ("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 opacity-60 hover:opacity-100"
            >
              <X size={12} weight="bold" />
            </button>
          )}
        </div>
        <label className="flex items-center gap-1.5 text-[12px]">
          <Funnel size={14} weight="duotone" className="opacity-70" />
          <span className="sr-only">Kind</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            aria-label="Filter by kind"
            className="rounded-md border px-2 py-1.5 text-[12px] bg-white"
            style={{ borderColor: "var(--color-rule)" }}
          >
            {KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-flex items-center gap-1.5 text-[12px] select-none">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
            className="accent-current"
          />
          Unread only
        </label>
        {filtersActive && (
          <button
            type="button"
            onClick={clearFilters}
            className="text-[12px] underline opacity-70 hover:opacity-100"
          >
            Reset
          </button>
        )}
      </div>

      <NotificationPrefsCard />

      <div className="flex items-center justify-between text-[11px] opacity-70 mb-2 mt-1 num">
        <span>
          {loading
            ? "Searching"
            : filtersActive
              ? `${matched} of ${total} match`
              : `${total} total`}
        </span>
        {page && (
          <span>
            Showing {items.length} of {matched}
          </span>
        )}
      </div>

      <div
        className="rounded-md border overflow-hidden"
        style={{ borderColor: "var(--color-rule)" }}
      >
        {loading && items.length === 0 ? (
          <Skeleton />
        ) : error ? (
          <div className="px-4 py-10 text-center">
            <Warning
              size={24}
              weight="duotone"
              className="mx-auto mb-2"
              style={{ color: "#b45309" }}
            />
            <div className="text-[13px] font-medium mb-1">
              Could not load notifications
            </div>
            <div className="text-[12px] opacity-70 mb-3">{error}</div>
            <button
              onClick={reload}
              className="text-[12px] underline"
              style={{ color: "var(--color-felt)" }}
            >
              Retry
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-14 text-center">
            <BellSlash
              size={28}
              weight="duotone"
              className="mx-auto mb-2 opacity-60"
            />
            <div className="text-[13px] font-medium mb-1">
              {filtersActive
                ? "No notifications match these filters"
                : "Inbox zero"}
            </div>
            <div className="text-[12px] opacity-70">
              {filtersActive
                ? "Try clearing the filters or a wider search."
                : "When you run a classification or a webhook fails, it shows up here."}
            </div>
            {filtersActive ? (
              <button
                onClick={clearFilters}
                className="inline-block mt-3 text-[12px] underline"
                style={{ color: "var(--color-felt)" }}
              >
                Reset filters
              </button>
            ) : (
              <Link
                href="/demo"
                className="inline-block mt-3 text-[12px] underline"
                style={{ color: "var(--color-felt)" }}
              >
                Try a classification
              </Link>
            )}
          </div>
        ) : (
          <>
            <ul>
              {items.map((n) => (
                <li
                  key={n.id}
                  className="border-b last:border-b-0"
                  style={{ borderColor: "var(--color-rule)" }}
                >
                  <div className="flex items-start gap-3 px-4 py-3">
                    <div className="pt-0.5">{kindIcon(n.kind)}</div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[13px] font-semibold truncate">
                          {n.title}
                        </span>
                        {!n.read_at ? (
                          <span
                            className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide"
                            style={{
                              background: "var(--color-felt)",
                              color: "var(--color-chalk)",
                            }}
                          >
                            New
                          </span>
                        ) : null}
                        <span className="eyebrow opacity-60">
                          {n.kind.replace(".", " · ")}
                        </span>
                      </div>
                      <div className="text-[12.5px] opacity-80 mt-0.5 break-words">
                        {n.body}
                      </div>
                      <div className="text-[11px] opacity-50 mt-1">
                        {fmt(n.created_at)}
                        {n.read_at ? " · read" : ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {n.href ? (
                        <Link
                          href={n.href}
                          onClick={() => !n.read_at && markRead(n.id)}
                          className="inline-flex items-center gap-1 text-[11.5px] px-2 py-1 rounded hover:bg-[color:var(--color-rule)]/40"
                        >
                          <ArrowSquareOut size={12} weight="duotone" /> Open
                        </Link>
                      ) : null}
                      {!n.read_at ? (
                        <button
                          onClick={() => markRead(n.id)}
                          disabled={busy}
                          aria-label="Mark as read"
                          className="inline-flex items-center justify-center w-7 h-7 rounded hover:bg-[color:var(--color-rule)]/40"
                        >
                          <Check size={13} weight="duotone" />
                        </button>
                      ) : null}
                      <button
                        onClick={() => remove(n.id)}
                        disabled={busy}
                        aria-label="Delete notification"
                        className="inline-flex items-center justify-center w-7 h-7 rounded hover:bg-[color:var(--color-rule)]/40"
                      >
                        <Trash size={13} weight="duotone" />
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            {page?.next_cursor != null && (
              <div
                className="px-4 py-3 flex justify-center border-t"
                style={{ borderColor: "var(--color-rule)" }}
              >
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={loadingMore}
                  className="inline-flex items-center gap-1.5 text-[12px] px-3 py-1.5 rounded-md border disabled:opacity-50"
                  style={{ borderColor: "var(--color-rule)" }}
                >
                  {loadingMore ? (
                    <>
                      <CircleNotch
                        size={12}
                        weight="bold"
                        className="animate-spin"
                      />
                      Loading
                    </>
                  ) : (
                    <>Load more</>
                  )}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
