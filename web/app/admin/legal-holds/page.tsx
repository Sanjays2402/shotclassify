"use client";

// Workspace legal hold console.
//
// While at least one matter is active, every destructive code path in the
// API refuses with HTTP 423 Locked: per-shot DELETE, bulk history DELETE,
// /v1/me/data and /v1/workspace/data erasure, and the scheduled retention
// purge. Lifting a hold writes lifted_at / lifted_by instead of deleting
// the row so the e-discovery audit trail survives.

import { useCallback, useState } from "react";
import useSWR from "swr";
import {
  Gavel,
  Plus,
  ShieldCheck,
  Warning,
  Clock,
  ArrowsClockwise,
  CheckCircle,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Hold = {
  id: string;
  tenant_id: string;
  matter: string;
  reason: string;
  created_by: string | null;
  created_at: string;
  lifted_at: string | null;
  lifted_by: string | null;
  lifted_reason: string | null;
  active: boolean;
};

type ListResp = {
  tenant_id: string;
  active: boolean;
  active_count: number;
  holds: Hold[];
};

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function LegalHoldsPage() {
  const { data, error, isLoading, mutate } = useSWR<ListResp>(
    "/api/settings/security/legal-holds",
    fetcher,
  );
  const [matter, setMatter] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const create = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!matter.trim()) {
        setErrMsg("Matter is required.");
        return;
      }
      setBusy(true);
      setErrMsg(null);
      try {
        const r = await fetch("/api/settings/security/legal-holds", {
          method: "POST",
          headers: { "content-type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ matter: matter.trim(), reason: reason.trim() }),
        });
        if (!r.ok) {
          const text = await r.text();
          setErrMsg(text || `${r.status} ${r.statusText}`);
          return;
        }
        setMatter("");
        setReason("");
        setFlash("Hold placed. Deletes are now blocked for this workspace.");
        mutate();
      } finally {
        setBusy(false);
      }
    },
    [matter, reason, mutate],
  );

  const lift = useCallback(
    async (id: string, matterName: string) => {
      const lifted_reason = window.prompt(
        `Lift hold for matter "${matterName}"? Enter a reason (optional):`,
        "",
      );
      if (lifted_reason === null) return;
      setBusy(true);
      setErrMsg(null);
      try {
        const r = await fetch(
          `/api/settings/security/legal-holds/${encodeURIComponent(id)}/lift`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ reason: lifted_reason }),
          },
        );
        if (!r.ok) {
          const text = await r.text();
          setErrMsg(text || `${r.status} ${r.statusText}`);
          return;
        }
        setFlash(`Lifted hold for "${matterName}".`);
        mutate();
      } finally {
        setBusy(false);
      }
    },
    [mutate],
  );

  if (error && (error as { status?: number }).status === 403) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 text-sm">
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6 bg-white dark:bg-neutral-950">
          <div className="flex items-center gap-2 text-neutral-700 dark:text-neutral-300">
            <ShieldCheck size={18} weight="duotone" />
            <span className="font-medium">Admin access required</span>
          </div>
          <p className="mt-2 text-neutral-500 dark:text-neutral-400">
            Only workspace admins can place or lift legal holds.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-neutral-900 dark:text-neutral-100">
            <Gavel size={22} weight="duotone" /> Legal holds
          </h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            Freeze every destructive operation while a matter is active.
            Retention purge, per-shot delete, bulk delete, and workspace
            erasure all return 423 Locked until the last hold is lifted.
          </p>
        </div>
        <button
          type="button"
          onClick={() => mutate()}
          className="inline-flex items-center gap-1 rounded-md border border-neutral-200 dark:border-neutral-800 px-2.5 py-1.5 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-900"
          aria-label="Refresh"
        >
          <ArrowsClockwise size={14} weight="duotone" /> Refresh
        </button>
      </header>

      {data && data.active ? (
        <div
          role="status"
          className="mb-5 flex items-start gap-2 rounded-md border border-amber-300 dark:border-amber-800/60 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-900 dark:text-amber-200"
        >
          <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
          <div>
            <strong className="font-medium">
              {data.active_count} active{" "}
              {data.active_count === 1 ? "hold" : "holds"}.
            </strong>{" "}
            Deletion is blocked for workspace{" "}
            <code className="rounded bg-amber-100 dark:bg-amber-900/40 px-1">
              {data.tenant_id}
            </code>
            .
          </div>
        </div>
      ) : null}

      {flash ? (
        <div
          role="status"
          className="mb-4 flex items-center gap-2 rounded-md border border-emerald-300 dark:border-emerald-800/60 bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-900 dark:text-emerald-200"
        >
          <CheckCircle size={16} weight="duotone" /> {flash}
        </div>
      ) : null}
      {errMsg ? (
        <div
          role="alert"
          className="mb-4 flex items-center gap-2 rounded-md border border-rose-300 dark:border-rose-800/60 bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-900 dark:text-rose-200"
        >
          <Warning size={16} weight="duotone" /> {errMsg}
        </div>
      ) : null}

      <section className="mb-6 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950">
        <header className="border-b border-neutral-200 dark:border-neutral-800 px-4 py-3 text-sm font-medium text-neutral-700 dark:text-neutral-300">
          Place new hold
        </header>
        <form className="space-y-3 p-4" onSubmit={create}>
          <div>
            <label
              htmlFor="hold-matter"
              className="mb-1 block text-xs font-medium text-neutral-700 dark:text-neutral-300"
            >
              Matter
            </label>
            <input
              id="hold-matter"
              type="text"
              required
              maxLength={256}
              value={matter}
              onChange={(e) => setMatter(e.target.value)}
              placeholder="e.g. SEC Inquiry 12-345"
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label
              htmlFor="hold-reason"
              className="mb-1 block text-xs font-medium text-neutral-700 dark:text-neutral-300"
            >
              Reason (optional)
            </label>
            <textarea
              id="hold-reason"
              rows={2}
              maxLength={4000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Counsel instruction, ticket link, regulator reference."
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="submit"
              disabled={busy || !matter.trim()}
              className="inline-flex items-center gap-1 rounded-md bg-neutral-900 dark:bg-neutral-100 px-3 py-1.5 text-sm font-medium text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50"
            >
              <Plus size={14} weight="duotone" /> Place hold
            </button>
          </div>
        </form>
      </section>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950">
        <header className="flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800 px-4 py-3 text-sm font-medium text-neutral-700 dark:text-neutral-300">
          <span>All holds</span>
          {data ? (
            <span className="text-xs text-neutral-500 dark:text-neutral-400">
              {data.holds.length} total
            </span>
          ) : null}
        </header>
        {isLoading ? (
          <div className="space-y-2 p-4" aria-busy="true">
            <div className="h-4 w-2/3 animate-pulse rounded bg-neutral-200 dark:bg-neutral-800" />
            <div className="h-4 w-1/2 animate-pulse rounded bg-neutral-200 dark:bg-neutral-800" />
            <div className="h-4 w-3/5 animate-pulse rounded bg-neutral-200 dark:bg-neutral-800" />
          </div>
        ) : !data || data.holds.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-8 text-center">
            <Gavel
              size={28}
              weight="duotone"
              className="text-neutral-400 dark:text-neutral-600"
            />
            <div className="text-sm text-neutral-700 dark:text-neutral-300">
              No legal holds on this workspace.
            </div>
            <div className="text-xs text-neutral-500 dark:text-neutral-400">
              Place a hold above when counsel or a regulator requires
              evidence preservation.
            </div>
          </div>
        ) : (
          <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {data.holds.map((h) => (
              <li
                key={h.id}
                className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className={
                        h.active
                          ? "inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/40 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:text-amber-200"
                          : "inline-flex items-center gap-1 rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-[11px] font-medium text-neutral-600 dark:text-neutral-400"
                      }
                    >
                      {h.active ? "Active" : "Lifted"}
                    </span>
                    <span className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">
                      {h.matter}
                    </span>
                  </div>
                  {h.reason ? (
                    <div className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">
                      {h.reason}
                    </div>
                  ) : null}
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-neutral-500 dark:text-neutral-400">
                    <span className="inline-flex items-center gap-1">
                      <Clock size={11} weight="duotone" /> placed{" "}
                      {fmt(h.created_at)}
                      {h.created_by ? ` by ${h.created_by}` : null}
                    </span>
                    {h.lifted_at ? (
                      <span className="inline-flex items-center gap-1">
                        <CheckCircle size={11} weight="duotone" /> lifted{" "}
                        {fmt(h.lifted_at)}
                        {h.lifted_by ? ` by ${h.lifted_by}` : null}
                        {h.lifted_reason ? ` · ${h.lifted_reason}` : null}
                      </span>
                    ) : null}
                  </div>
                </div>
                {h.active ? (
                  <button
                    type="button"
                    onClick={() => lift(h.id, h.matter)}
                    disabled={busy}
                    className="self-start rounded-md border border-neutral-200 dark:border-neutral-800 px-2.5 py-1 text-xs font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-900 disabled:opacity-50"
                  >
                    Lift hold
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
