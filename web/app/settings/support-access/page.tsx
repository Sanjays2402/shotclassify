"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Lifebuoy,
  ShieldCheck,
  Clock,
  Trash,
  Warning,
  CheckCircle,
  Plus,
  Lock,
  User,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Grant = {
  id: string;
  tenant_id: string;
  reason: string;
  allowed_admin: string | null;
  created_by: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  revoked_by: string | null;
  last_used_at: string | null;
  use_count: number;
  active: boolean;
};

type GrantsResponse = {
  grants: Grant[];
  tenant_id: string;
  policy: { min_minutes: number; max_minutes: number };
};

type ApiError = Error & { status?: number };

function formatWhen(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleString(undefined, {
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

function expiresIn(iso: string): string {
  try {
    const ms = new Date(iso).getTime() - Date.now();
    if (ms <= 0) return "expired";
    const min = Math.round(ms / 60_000);
    if (min < 60) return `in ${min}m`;
    const h = Math.floor(min / 60);
    const rem = min % 60;
    if (h < 24) return rem ? `in ${h}h ${rem}m` : `in ${h}h`;
    const d = Math.floor(h / 24);
    return `in ${d}d ${h % 24}h`;
  } catch {
    return "";
  }
}

const DURATION_PRESETS: { label: string; minutes: number }[] = [
  { label: "30 minutes", minutes: 30 },
  { label: "1 hour", minutes: 60 },
  { label: "4 hours", minutes: 240 },
  { label: "24 hours", minutes: 1440 },
  { label: "7 days", minutes: 7 * 1440 },
];

export default function SupportAccessPage() {
  const { data, error, isLoading, mutate } = useSWR<GrantsResponse>(
    "/api/support-access?include_inactive=true&limit=100",
    fetcher,
    { revalidateOnFocus: true, refreshInterval: 60_000 },
  );

  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [allowedAdmin, setAllowedAdmin] = useState("");
  const [submitBusy, setSubmitBusy] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;
  const grants = data?.grants ?? [];
  const activeGrants = useMemo(() => grants.filter((g) => g.active), [grants]);
  const policy = data?.policy;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFlash(null);
    if (reason.trim().length < 3) {
      setFlash({ kind: "err", msg: "Reason must be at least 3 characters." });
      return;
    }
    setSubmitBusy(true);
    try {
      const r = await fetch("/api/support-access", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          reason: reason.trim(),
          duration_minutes: minutes,
          allowed_admin: allowedAdmin.trim() || null,
        }),
      });
      if (!r.ok) throw new Error((await r.text()) || `${r.status}`);
      setReason("");
      setAllowedAdmin("");
      setFlash({ kind: "ok", msg: "Grant created. Vendor admin access is now authorized." });
      await mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Create grant failed." });
    } finally {
      setSubmitBusy(false);
    }
  };

  const revoke = async (id: string) => {
    setBusyId(id);
    setFlash(null);
    try {
      const r = await fetch(`/api/support-access/${encodeURIComponent(id)}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (!r.ok) throw new Error((await r.text()) || `${r.status}`);
      setFlash({ kind: "ok", msg: "Grant revoked." });
      await mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Revoke failed." });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="mb-6 flex flex-col gap-2 sm:mb-8">
        <div className="flex items-center gap-3">
          <Lifebuoy size={28} weight="duotone" className="text-emerald-500" />
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Support access
          </h1>
        </div>
        <p className="max-w-2xl text-sm text-zinc-500 dark:text-zinc-400">
          Vendor administrators cannot read or change your workspace data
          unless you have an active grant on file. Each grant is time-boxed,
          carries a reason you control, and is recorded in the immutable
          audit log.
        </p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-zinc-200 bg-zinc-50/60 px-4 py-3 text-sm dark:border-zinc-800 dark:bg-zinc-900/40">
        <ShieldCheck size={20} weight="duotone" className="text-emerald-500" />
        <span className="font-medium">
          {activeGrants.length} active grant{activeGrants.length === 1 ? "" : "s"}
        </span>
        <span className="text-zinc-400">·</span>
        <span className="text-zinc-500 dark:text-zinc-400">
          Without an active grant, all cross-tenant admin requests return 403.
        </span>
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
          Sign in as a workspace admin to manage support access grants.
        </div>
      )}
      {forbidden && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-6 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
          Your role cannot manage support access. Ask a workspace admin.
        </div>
      )}

      {!unauth && !forbidden && (
        <form
          onSubmit={submit}
          className="mb-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950"
        >
          <div className="mb-4 flex items-center gap-2">
            <Plus size={18} weight="duotone" className="text-emerald-500" />
            <h2 className="text-sm font-semibold">Authorize vendor access</h2>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="sm:col-span-2 text-sm">
              <span className="mb-1 block text-zinc-600 dark:text-zinc-300">
                Reason (ticket id, short narrative)
              </span>
              <input
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={1024}
                placeholder="ZD-12345 investigate failed classify run"
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-zinc-600 dark:text-zinc-300">
                Duration
              </span>
              <select
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900"
              >
                {DURATION_PRESETS.map((p) => (
                  <option key={p.minutes} value={p.minutes}>
                    {p.label}
                  </option>
                ))}
              </select>
              {policy && (
                <span className="mt-1 block text-xs text-zinc-500">
                  Max {Math.round(policy.max_minutes / 60)}h per grant.
                </span>
              )}
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-zinc-600 dark:text-zinc-300">
                Pin to admin login (optional)
              </span>
              <input
                type="text"
                value={allowedAdmin}
                onChange={(e) => setAllowedAdmin(e.target.value)}
                maxLength={256}
                placeholder="support.engineer@vendor.example"
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900"
              />
              <span className="mt-1 block text-xs text-zinc-500">
                Empty means any vendor admin may use this grant.
              </span>
            </label>
          </div>
          <div className="mt-4 flex justify-end">
            <button
              type="submit"
              disabled={submitBusy}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Lock size={16} weight="duotone" />
              {submitBusy ? "Creating..." : "Create grant"}
            </button>
          </div>
        </form>
      )}

      {!unauth && !forbidden && isLoading && (
        <ul className="space-y-2">
          {[0, 1, 2].map((i) => (
            <li
              key={i}
              className="h-24 animate-pulse rounded-xl border border-zinc-200 bg-zinc-100/60 dark:border-zinc-800 dark:bg-zinc-900/40"
            />
          ))}
        </ul>
      )}

      {!unauth && !forbidden && !isLoading && grants.length === 0 && (
        <div className="rounded-xl border border-dashed border-zinc-300 p-10 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          No support access has ever been granted for this workspace.
        </div>
      )}

      {!unauth && !forbidden && grants.length > 0 && (
        <ul className="space-y-2">
          {grants.map((g) => (
            <li
              key={g.id}
              className={`rounded-xl border p-4 transition ${
                g.active
                  ? "border-emerald-300 bg-emerald-50/40 dark:border-emerald-800/60 dark:bg-emerald-950/20"
                  : "border-zinc-200 bg-zinc-50 opacity-80 dark:border-zinc-800 dark:bg-zinc-900/40"
              }`}
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium">{g.reason}</span>
                    {g.active ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
                        <CheckCircle size={12} weight="duotone" />
                        Active
                      </span>
                    ) : (
                      <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                        {g.revoked_at ? "Revoked" : "Expired"}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
                    <span className="inline-flex items-center gap-1">
                      <Clock size={12} weight="duotone" />
                      {g.active
                        ? `Expires ${expiresIn(g.expires_at)} (${formatWhen(g.expires_at)})`
                        : `Expired ${formatWhen(g.expires_at)}`}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <User size={12} weight="duotone" />
                      Created by {g.created_by}
                    </span>
                    {g.allowed_admin && (
                      <span className="inline-flex items-center gap-1">
                        <Lock size={12} weight="duotone" />
                        Pinned to {g.allowed_admin}
                      </span>
                    )}
                    <span>
                      Used {g.use_count}x
                      {g.last_used_at ? ` (last ${formatWhen(g.last_used_at)})` : ""}
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-400">id {g.id}</div>
                </div>
                {g.active && (
                  <button
                    type="button"
                    onClick={() => revoke(g.id)}
                    disabled={busyId === g.id}
                    className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-900/60 dark:bg-zinc-950 dark:text-rose-300 dark:hover:bg-rose-950/30"
                    aria-label="Revoke grant"
                  >
                    <Trash size={14} weight="duotone" />
                    {busyId === g.id ? "Revoking..." : "Revoke"}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
