"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  Bell,
  BellSlash,
  CheckCircle,
  Warning,
  Info,
  Trash,
  Check,
  ArrowSquareOut,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";
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

type Feed = { items: Notif[]; unread: number };

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
      <Warning
        size={18}
        weight="duotone"
        style={{ color: "#b45309" }}
      />
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

export default function NotificationsPage() {
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [busy, setBusy] = useState(false);
  const { data, error, isLoading, mutate } = useSWR<Feed>(
    "/api/notifications?limit=200",
    fetcher,
    { refreshInterval: 20_000 },
  );

  const items = (data?.items ?? []).filter((n) =>
    filter === "unread" ? !n.read_at : true,
  );
  const unread = data?.unread ?? 0;

  const markRead = async (id: string) => {
    setBusy(true);
    await fetch(`/api/notifications/${id}`, { method: "PATCH" });
    await mutate();
    setBusy(false);
  };
  const remove = async (id: string) => {
    setBusy(true);
    await fetch(`/api/notifications/${id}`, { method: "DELETE" });
    await mutate();
    setBusy(false);
  };
  const markAllRead = async () => {
    setBusy(true);
    await fetch("/api/notifications", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "mark_all_read" }),
    });
    await mutate();
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
    await mutate();
    setBusy(false);
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
        <div className="flex items-center gap-2">
          <div
            role="tablist"
            aria-label="Filter notifications"
            className="inline-flex rounded-md border overflow-hidden"
            style={{ borderColor: "var(--color-rule)" }}
          >
            {(["all", "unread"] as const).map((f) => (
              <button
                key={f}
                role="tab"
                aria-selected={filter === f}
                onClick={() => setFilter(f)}
                className="px-3 py-1.5 text-[12px] capitalize"
                style={{
                  background:
                    filter === f
                      ? "var(--color-felt)"
                      : "transparent",
                  color:
                    filter === f
                      ? "var(--color-chalk)"
                      : "inherit",
                }}
              >
                {f}
              </button>
            ))}
          </div>
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
            disabled={busy || (data?.items?.length ?? 0) === 0}
            className="inline-flex items-center gap-1 text-[12px] px-2.5 py-1.5 rounded-md border disabled:opacity-40"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <Trash size={14} weight="duotone" /> Clear all
          </button>
        </div>
      </div>

      <NotificationPrefsCard />

      <div
        className="rounded-md border overflow-hidden"
        style={{ borderColor: "var(--color-rule)" }}
      >
        {isLoading ? (
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
            <div className="text-[12px] opacity-70 mb-3">
              {(error as Error).message}
            </div>
            <button
              onClick={() => mutate()}
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
              {filter === "unread"
                ? "No unread notifications"
                : "Inbox zero"}
            </div>
            <div className="text-[12px] opacity-70">
              When you run a classification or a webhook fails, it shows up here.
            </div>
            <Link
              href="/demo"
              className="inline-block mt-3 text-[12px] underline"
              style={{ color: "var(--color-felt)" }}
            >
              Try a classification
            </Link>
          </div>
        ) : (
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
                    <div className="text-[12.5px] opacity-80 mt-0.5">
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
        )}
      </div>
    </div>
  );
}
