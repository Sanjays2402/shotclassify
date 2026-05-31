"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  Devices,
  SignOut,
  Trash,
  Warning,
  CheckCircle,
  Clock,
  Globe,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type SessionRow = {
  id: string;
  principal: string;
  tenant_id: string | null;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  revoked_at: string | null;
  client_ip: string | null;
  user_agent: string | null;
  current: boolean;
};

type SessionsResponse = {
  sessions: SessionRow[];
  current: string | null;
};

type ApiError = Error & { status?: number };

function formatWhen(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function relative(iso: string): string {
  try {
    const then = new Date(iso).getTime();
    const diffSec = Math.round((Date.now() - then) / 1000);
    if (diffSec < 60) return "just now";
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return `${Math.floor(diffSec / 86400)}d ago`;
  } catch {
    return "";
  }
}

function shortenAgent(ua: string | null): string {
  if (!ua) return "Unknown device";
  // Pull the first browser-ish token. Avoids dumping the whole UA in the table.
  const m = ua.match(/(Firefox|Chrome|Safari|Edge|OPR|Opera|curl|python|httpx|pytest)[\/-]?[\w.]*/i);
  const os = ua.match(/(Mac OS X [\d_.]+|Windows [\w. ]+|Linux|iPhone OS [\d_]+|Android [\d.]+|iPad)/);
  const parts = [m?.[0], os?.[0]].filter(Boolean);
  return parts.length ? parts.join(" on ") : ua.slice(0, 64);
}

export default function SessionsPage() {
  const { data, error, isLoading, mutate } = useSWR<SessionsResponse>(
    "/api/sessions",
    fetcher,
    { revalidateOnFocus: true, refreshInterval: 30_000 },
  );

  const [busyId, setBusyId] = useState<string | null>(null);
  const [revokeAllBusy, setRevokeAllBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const sessions = data?.sessions ?? [];
  const activeCount = sessions.filter((s) => !s.revoked_at).length;

  const revoke = async (id: string) => {
    setBusyId(id);
    setFlash(null);
    try {
      const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (!r.ok) throw new Error((await r.text()) || `${r.status}`);
      setFlash({ kind: "ok", msg: "Session revoked." });
      await mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Revoke failed." });
    } finally {
      setBusyId(null);
    }
  };

  const revokeAllOther = async () => {
    if (
      !confirm(
        "Log out every other device signed in to this account? You will stay signed in here.",
      )
    )
      return;
    setRevokeAllBusy(true);
    setFlash(null);
    try {
      const r = await fetch(`/api/sessions/revoke-all?keep_current=true`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (!r.ok) throw new Error((await r.text()) || `${r.status}`);
      const body = (await r.json()) as { revoked: number };
      setFlash({
        kind: "ok",
        msg:
          body.revoked === 0
            ? "No other active sessions to revoke."
            : `Revoked ${body.revoked} other session${body.revoked === 1 ? "" : "s"}.`,
      });
      await mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Revoke all failed." });
    } finally {
      setRevokeAllBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="mb-6 flex flex-col gap-2 sm:mb-8">
        <div className="flex items-center gap-3">
          <Devices size={28} weight="duotone" className="text-emerald-500" />
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Active sessions
          </h1>
        </div>
        <p className="max-w-2xl text-sm text-zinc-500 dark:text-zinc-400">
          Every browser session signed in to this account. Revoke any device you
          do not recognise, or sign every other device out at once if you think
          your account was compromised.
        </p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-zinc-200 bg-zinc-50/60 px-4 py-3 text-sm dark:border-zinc-800 dark:bg-zinc-900/40">
        <ShieldCheck
          size={20}
          weight="duotone"
          className="text-emerald-500"
        />
        <span className="font-medium">
          {activeCount} active session{activeCount === 1 ? "" : "s"}
        </span>
        <span className="text-zinc-400">·</span>
        <span className="text-zinc-500 dark:text-zinc-400">
          Sessions expire automatically after 30 days of inactivity.
        </span>
        <div className="ml-auto">
          <button
            type="button"
            onClick={revokeAllOther}
            disabled={revokeAllBusy || activeCount <= 1}
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
          >
            <SignOut size={16} weight="duotone" />
            {revokeAllBusy ? "Signing out..." : "Sign out other devices"}
          </button>
        </div>
      </div>

      {flash && (
        <div
          role="status"
          className={`mb-4 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-200"
              : "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200"
          }`}
        >
          {flash.kind === "ok" ? (
            <CheckCircle size={18} weight="duotone" />
          ) : (
            <Warning size={18} weight="duotone" />
          )}
          <span>{flash.msg}</span>
        </div>
      )}

      {unauth && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-6 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
          You need to sign in before you can manage sessions. Sessions only
          exist for browser logins; API keys do not create sessions.
        </div>
      )}

      {!unauth && isLoading && (
        <ul className="space-y-2">
          {[0, 1, 2].map((i) => (
            <li
              key={i}
              className="h-20 animate-pulse rounded-xl border border-zinc-200 bg-zinc-100/60 dark:border-zinc-800 dark:bg-zinc-900/40"
            />
          ))}
        </ul>
      )}

      {!unauth && !isLoading && sessions.length === 0 && (
        <div className="rounded-xl border border-dashed border-zinc-300 p-10 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          No active sessions found for this account.
        </div>
      )}

      {!unauth && sessions.length > 0 && (
        <ul className="space-y-2">
          {sessions.map((s) => {
            const revoked = !!s.revoked_at;
            return (
              <li
                key={s.id}
                className={`rounded-xl border p-4 transition ${
                  revoked
                    ? "border-zinc-200 bg-zinc-50 opacity-60 dark:border-zinc-800 dark:bg-zinc-900/40"
                    : s.current
                      ? "border-emerald-400 bg-emerald-50/40 dark:border-emerald-700/60 dark:bg-emerald-950/20"
                      : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950"
                }`}
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium">
                        {shortenAgent(s.user_agent)}
                      </span>
                      {s.current && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
                          <CheckCircle size={12} weight="duotone" />
                          This device
                        </span>
                      )}
                      {revoked && (
                        <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                          Revoked
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
                      <span className="inline-flex items-center gap-1">
                        <Globe size={12} weight="duotone" />
                        {s.client_ip ?? "Unknown IP"}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Clock size={12} weight="duotone" />
                        Last active {relative(s.last_seen_at)}
                      </span>
                      <span title={`Created ${formatWhen(s.created_at)}`}>
                        Signed in {formatWhen(s.created_at)}
                      </span>
                    </div>
                  </div>
                  {!revoked && (
                    <button
                      type="button"
                      onClick={() => revoke(s.id)}
                      disabled={busyId === s.id}
                      className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-900/60 dark:bg-zinc-950 dark:text-rose-300 dark:hover:bg-rose-950/30"
                      aria-label={s.current ? "Sign out this device" : "Revoke session"}
                    >
                      <Trash size={14} weight="duotone" />
                      {busyId === s.id
                        ? "Revoking..."
                        : s.current
                          ? "Sign out"
                          : "Revoke"}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
