"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Bell, BellRinging, Check, X } from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

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

function rel(iso: string): string {
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<string | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const { data, mutate } = useSWR<Feed>("/api/notifications?limit=20", fetcher, {
    refreshInterval: 15_000,
    revalidateOnFocus: true,
  });

  const items = data?.items ?? [];
  const unread = data?.unread ?? 0;

  // Toast: when the freshest id changes (and is unread), show a small toast.
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [toast, setToast] = useState<Notif | null>(null);
  useEffect(() => {
    if (!items.length) return;
    const newest = items[0];
    if (!lastSeen) {
      setLastSeen(newest.id);
      return;
    }
    if (newest.id !== lastSeen && !newest.read_at) {
      setToast(newest);
      if (toastTimer.current) clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToast(null), 5000);
    }
    setLastSeen(newest.id);
  }, [items, lastSeen]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const markAllRead = async () => {
    await fetch("/api/notifications", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "mark_all_read" }),
    });
    mutate();
  };

  const Icon = unread > 0 ? BellRinging : Bell;

  return (
    <>
      <div className="relative">
        <button
          aria-label={`Notifications${unread > 0 ? `, ${unread} unread` : ""}`}
          onClick={() => setOpen((v) => !v)}
          className="relative inline-flex items-center justify-center w-8 h-8 rounded-md hover:bg-[color:var(--color-rule)]/40 transition-colors"
          style={{ color: "var(--color-felt)" }}
        >
          <Icon size={18} weight="duotone" />
          {unread > 0 ? (
            <span
              className="absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] px-1 rounded-full text-[10px] font-semibold flex items-center justify-center"
              style={{
                background: "var(--color-felt)",
                color: "var(--color-chalk)",
              }}
            >
              {unread > 99 ? "99+" : unread}
            </span>
          ) : null}
        </button>
        {open ? (
          <div
            ref={popoverRef}
            role="dialog"
            aria-label="Notifications"
            className="absolute right-0 mt-2 w-[min(360px,calc(100vw-2rem))] rounded-md border shadow-lg z-50"
            style={{
              background: "var(--color-chalk)",
              borderColor: "var(--color-rule)",
            }}
          >
            <div
              className="flex items-center justify-between px-3 py-2 border-b"
              style={{ borderColor: "var(--color-rule)" }}
            >
              <span className="text-[13px] font-semibold">Notifications</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={markAllRead}
                  disabled={unread === 0}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded disabled:opacity-40 hover:bg-[color:var(--color-rule)]/40"
                >
                  <Check size={12} weight="duotone" /> Mark all read
                </button>
                <Link
                  href="/notifications"
                  onClick={() => setOpen(false)}
                  className="text-[11px] px-2 py-1 rounded hover:bg-[color:var(--color-rule)]/40"
                >
                  View all
                </Link>
              </div>
            </div>
            <div className="max-h-[360px] overflow-y-auto">
              {items.length === 0 ? (
                <div className="px-3 py-6 text-center text-[12px] opacity-60">
                  No notifications yet. Activity will land here.
                </div>
              ) : (
                <ul>
                  {items.slice(0, 8).map((n) => (
                    <li
                      key={n.id}
                      className="border-b last:border-b-0"
                      style={{ borderColor: "var(--color-rule)" }}
                    >
                      <Link
                        href={n.href || "/notifications"}
                        onClick={async () => {
                          setOpen(false);
                          if (!n.read_at) {
                            await fetch(`/api/notifications/${n.id}`, {
                              method: "PATCH",
                            });
                            mutate();
                          }
                        }}
                        className="block px-3 py-2 hover:bg-[color:var(--color-rule)]/30"
                      >
                        <div className="flex items-start gap-2">
                          {!n.read_at ? (
                            <span
                              className="mt-1.5 inline-block w-1.5 h-1.5 rounded-full shrink-0"
                              style={{ background: "var(--color-felt)" }}
                              aria-hidden
                            />
                          ) : (
                            <span className="mt-1.5 inline-block w-1.5 h-1.5 shrink-0" />
                          )}
                          <div className="min-w-0 flex-1">
                            <div className="text-[12.5px] font-medium truncate">
                              {n.title}
                            </div>
                            <div className="text-[11.5px] opacity-70 line-clamp-2">
                              {n.body}
                            </div>
                            <div className="text-[10.5px] opacity-50 mt-0.5">
                              {rel(n.created_at)}
                            </div>
                          </div>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : null}
      </div>

      {toast ? (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 right-4 z-[60] max-w-sm rounded-md border shadow-lg"
          style={{
            background: "var(--color-chalk)",
            borderColor: "var(--color-rule)",
          }}
        >
          <div className="flex items-start gap-3 px-3 py-2.5">
            <BellRinging
              size={18}
              weight="duotone"
              style={{ color: "var(--color-felt)" }}
            />
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold truncate">
                {toast.title}
              </div>
              <div className="text-[11.5px] opacity-70 line-clamp-2">
                {toast.body}
              </div>
              {toast.href ? (
                <Link
                  href={toast.href}
                  onClick={() => setToast(null)}
                  className="inline-block mt-1 text-[11px] underline"
                  style={{ color: "var(--color-felt)" }}
                >
                  Open
                </Link>
              ) : null}
            </div>
            <button
              aria-label="Dismiss notification"
              onClick={() => setToast(null)}
              className="opacity-50 hover:opacity-100"
            >
              <X size={14} weight="duotone" />
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
