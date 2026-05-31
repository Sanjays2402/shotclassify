"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { SlidersHorizontal, Check, Warning } from "@phosphor-icons/react/dist/ssr";

import { fetcher } from "@/lib/api";

type NotificationKind = "classify.completed" | "webhook.failed" | "system";

type Prefs = {
  enabled: Record<NotificationKind, boolean>;
  updated_at: string | null;
};

const ROWS: { kind: NotificationKind; title: string; body: string }[] = [
  {
    kind: "classify.completed",
    title: "Classification complete",
    body: "A shot finishes classifying and a result lands in your history.",
  },
  {
    kind: "webhook.failed",
    title: "Webhook delivery failed",
    body: "A webhook endpoint stops accepting deliveries after retries.",
  },
  {
    kind: "system",
    title: "System messages",
    body: "Operational notices from the platform itself.",
  },
];

export function NotificationPrefsCard() {
  const { data, error, isLoading, mutate } = useSWR<Prefs>(
    "/api/notifications/prefs",
    fetcher,
    { revalidateOnFocus: false },
  );
  const [local, setLocal] = useState<Record<NotificationKind, boolean> | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    if (data?.enabled && !local) setLocal({ ...data.enabled });
  }, [data, local]);

  const view = local ?? data?.enabled ?? null;
  const dirty =
    !!local &&
    !!data &&
    ROWS.some((r) => local[r.kind] !== data.enabled[r.kind]);

  const toggle = (k: NotificationKind) => {
    if (!view) return;
    setLocal({ ...view, [k]: !view[k] });
    setFlash(null);
  };

  const save = async () => {
    if (!local) return;
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/notifications/prefs", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: local }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      await mutate();
      setFlash({ kind: "ok", msg: "Preferences saved." });
    } catch (err) {
      setFlash({
        kind: "err",
        msg: err instanceof Error ? err.message : "Save failed",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="rounded-md border mb-4"
      style={{ borderColor: "var(--color-rule)" }}
      aria-labelledby="notif-prefs-heading"
    >
      <header
        className="flex items-center justify-between gap-3 px-4 py-3 border-b"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <SlidersHorizontal size={18} weight="duotone" />
          <h2
            id="notif-prefs-heading"
            className="text-[13px] font-semibold truncate"
          >
            Preferences
          </h2>
          <span className="text-[11px] opacity-60 hidden sm:inline">
            Mute the kinds you do not want in your inbox.
          </span>
        </div>
        <div className="flex items-center gap-2">
          {flash && (
            <span
              role="status"
              className="text-[11px] inline-flex items-center gap-1"
              style={{
                color: flash.kind === "ok" ? "var(--color-felt)" : "#b91c1c",
              }}
            >
              {flash.kind === "ok" ? (
                <Check size={12} weight="duotone" />
              ) : (
                <Warning size={12} weight="duotone" />
              )}
              {flash.msg}
            </span>
          )}
          <button
            onClick={save}
            disabled={!dirty || busy}
            className="inline-flex items-center gap-1 text-[12px] px-2.5 py-1.5 rounded-md border disabled:opacity-40"
            style={{ borderColor: "var(--color-rule)" }}
          >
            {busy ? "Saving..." : "Save"}
          </button>
        </div>
      </header>
      <div className="p-2">
        {isLoading || !view ? (
          <div className="animate-pulse p-2 space-y-2">
            {ROWS.map((r) => (
              <div
                key={r.kind}
                className="h-10 rounded"
                style={{ background: "var(--color-rule)" }}
              />
            ))}
          </div>
        ) : error ? (
          <div className="px-3 py-6 text-center text-[12px] opacity-70">
            Could not load preferences. {(error as Error).message}
          </div>
        ) : (
          <ul className="divide-y" style={{ borderColor: "var(--color-rule)" }}>
            {ROWS.map((r) => {
              const on = !!view[r.kind];
              return (
                <li
                  key={r.kind}
                  className="flex items-start justify-between gap-4 px-3 py-3"
                  style={{ borderColor: "var(--color-rule)" }}
                >
                  <div className="min-w-0">
                    <label
                      htmlFor={`pref-${r.kind}`}
                      className="text-[13px] font-medium cursor-pointer"
                    >
                      {r.title}
                    </label>
                    <div className="text-[12px] opacity-70 mt-0.5">{r.body}</div>
                    <code className="text-[10px] opacity-50">{r.kind}</code>
                  </div>
                  <button
                    id={`pref-${r.kind}`}
                    role="switch"
                    aria-checked={on}
                    aria-label={`${on ? "Disable" : "Enable"} ${r.title}`}
                    onClick={() => toggle(r.kind)}
                    className="shrink-0 relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1"
                    style={{
                      background: on
                        ? "var(--color-felt)"
                        : "var(--color-rule)",
                    }}
                  >
                    <span
                      className="inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform"
                      style={{
                        transform: on ? "translateX(18px)" : "translateX(2px)",
                      }}
                    />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
