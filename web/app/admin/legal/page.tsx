"use client";

// Legal agreements admin console.
//
// Workspace admins review the current Terms of Service, Data Processing
// Addendum, and Acceptable Use Policy, accept them on behalf of the
// workspace, and optionally arm a workspace-wide enforcement gate that
// blocks every mutating /v1 route with HTTP 451 until all required
// agreements have been accepted at their current version.

import { useCallback, useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  Scales,
  Warning,
  CheckCircle,
  ArrowsClockwise,
  ClipboardText,
  Lock,
  LockOpen,
  Clock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Acceptance = {
  id: string;
  tenant_id: string;
  agreement_id: string;
  version: string;
  accepted_by: string;
  accepted_at: string;
  accepted_ip: string | null;
  user_agent: string | null;
  request_id: string | null;
};

type AgreementStatus = {
  id: string;
  title: string;
  summary: string;
  required: boolean;
  current_version: string;
  accepted: boolean;
  stale: boolean;
  latest_acceptance: Acceptance | null;
};

type StatusResp = {
  tenant_id: string;
  enforcement: {
    tenant_id: string;
    enforce: boolean;
    updated_by: string | null;
    updated_at: string | null;
  };
  agreements: AgreementStatus[];
  missing_required: string[];
  all_required_accepted: boolean;
};

type CatalogResp = {
  agreements: Array<{
    id: string;
    title: string;
    summary: string;
    version: string;
    required: boolean;
    body: string;
  }>;
  required_ids: string[];
  count: number;
};

type LedgerResp = {
  tenant_id: string;
  count: number;
  entries: Acceptance[];
};

function fmt(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function LegalAgreementsPage() {
  const status = useSWR<StatusResp>("/api/trust/legal/status", fetcher);
  const catalog = useSWR<CatalogResp>("/api/trust/legal", fetcher);
  const ledger = useSWR<LedgerResp>("/api/trust/legal/ledger?limit=50", fetcher);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const refreshAll = useCallback(() => {
    status.mutate();
    catalog.mutate();
    ledger.mutate();
  }, [status, catalog, ledger]);

  const accept = useCallback(
    async (agreement_id: string, version: string, title: string) => {
      setBusy(agreement_id);
      setErrMsg(null);
      try {
        const r = await fetch("/api/trust/legal/accept", {
          method: "POST",
          headers: { "content-type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ agreement_id, version }),
        });
        if (!r.ok) {
          const text = await r.text();
          setErrMsg(text || `${r.status} ${r.statusText}`);
          return;
        }
        setFlash(`Accepted ${title} at version ${version.slice(0, 8)}.`);
        refreshAll();
      } finally {
        setBusy(null);
      }
    },
    [refreshAll],
  );

  const setEnforcement = useCallback(
    async (enforce: boolean) => {
      setBusy("enforcement");
      setErrMsg(null);
      try {
        const r = await fetch("/api/trust/legal/enforcement", {
          method: "PUT",
          headers: { "content-type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ enforce }),
        });
        if (!r.ok) {
          const text = await r.text();
          setErrMsg(text || `${r.status} ${r.statusText}`);
          return;
        }
        setFlash(
          enforce
            ? "Enforcement enabled. Mutating writes will block until acceptances are current."
            : "Enforcement disabled.",
        );
        refreshAll();
      } finally {
        setBusy(null);
      }
    },
    [refreshAll],
  );

  if (
    status.error &&
    (status.error as { status?: number }).status === 403
  ) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 text-sm">
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6 bg-white dark:bg-neutral-950">
          <div className="flex items-center gap-2 text-neutral-700 dark:text-neutral-300">
            <ShieldCheck size={18} weight="duotone" />
            <span className="font-medium">Admin access required</span>
          </div>
          <p className="mt-2 text-neutral-500 dark:text-neutral-400">
            Only workspace admins can accept legal agreements or change the
            enforcement policy.
          </p>
        </div>
      </main>
    );
  }

  const loading = status.isLoading || catalog.isLoading;
  const s = status.data;
  const c = catalog.data;
  const l = ledger.data;
  const bodyById = new Map<string, string>(
    (c?.agreements ?? []).map((a) => [a.id, a.body]),
  );

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-neutral-900 dark:text-neutral-100">
            <Scales size={22} weight="duotone" /> Legal agreements
          </h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            Review and accept the current Terms of Service, Data Processing
            Addendum, and Acceptable Use Policy on behalf of this workspace.
            Acceptances are recorded with actor, IP, and timestamp in an
            append-only ledger.
          </p>
        </div>
        <button
          type="button"
          onClick={refreshAll}
          className="inline-flex items-center gap-1 rounded-md border border-neutral-200 dark:border-neutral-800 px-2.5 py-1.5 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-900"
          aria-label="Refresh"
        >
          <ArrowsClockwise size={14} weight="duotone" /> Refresh
        </button>
      </header>

      {flash && (
        <div
          role="status"
          className="mb-4 flex items-start gap-2 rounded-md border border-emerald-300 dark:border-emerald-800/60 bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-900 dark:text-emerald-200"
        >
          <CheckCircle size={16} weight="duotone" className="mt-0.5 shrink-0" />
          <div className="flex-1">{flash}</div>
          <button
            type="button"
            onClick={() => setFlash(null)}
            className="text-xs underline"
          >
            dismiss
          </button>
        </div>
      )}
      {errMsg && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-md border border-rose-300 dark:border-rose-800/60 bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-900 dark:text-rose-200"
        >
          <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
          <div className="flex-1 break-words font-mono text-xs">{errMsg}</div>
          <button
            type="button"
            onClick={() => setErrMsg(null)}
            className="text-xs underline"
          >
            dismiss
          </button>
        </div>
      )}

      {loading && !s && (
        <div className="space-y-3" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-24 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900 animate-pulse"
            />
          ))}
        </div>
      )}

      {s && (
        <>
          <section
            aria-labelledby="enforcement-heading"
            className="mb-6 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2
                  id="enforcement-heading"
                  className="flex items-center gap-2 text-sm font-medium text-neutral-900 dark:text-neutral-100"
                >
                  {s.enforcement.enforce ? (
                    <Lock size={16} weight="duotone" />
                  ) : (
                    <LockOpen size={16} weight="duotone" />
                  )}
                  Enforcement gate
                </h2>
                <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                  When enabled, every mutating /v1 request from this workspace
                  is rejected with HTTP 451 until all required agreements have
                  been accepted at their current version.
                </p>
                {s.enforcement.updated_at && (
                  <p className="mt-2 text-[11px] text-neutral-500 dark:text-neutral-400">
                    Last changed by{" "}
                    <code>{s.enforcement.updated_by ?? "unknown"}</code> on{" "}
                    {fmt(s.enforcement.updated_at)}.
                  </p>
                )}
              </div>
              <div className="flex flex-col items-end gap-2">
                <span
                  className={
                    "rounded-full px-2 py-0.5 text-[11px] " +
                    (s.enforcement.enforce
                      ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-200"
                      : "bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400")
                  }
                >
                  {s.enforcement.enforce ? "armed" : "off"}
                </span>
                {s.enforcement.enforce ? (
                  <button
                    type="button"
                    disabled={busy === "enforcement"}
                    onClick={() => setEnforcement(false)}
                    className="inline-flex items-center gap-1 rounded-md border border-neutral-200 dark:border-neutral-800 px-2.5 py-1.5 text-xs hover:bg-neutral-50 dark:hover:bg-neutral-900 disabled:opacity-50"
                  >
                    <LockOpen size={12} weight="duotone" /> Disable
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={
                      busy === "enforcement" || !s.all_required_accepted
                    }
                    onClick={() => setEnforcement(true)}
                    title={
                      s.all_required_accepted
                        ? "Arm the gate"
                        : "Accept all required agreements before arming the gate."
                    }
                    className="inline-flex items-center gap-1 rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 px-2.5 py-1.5 text-xs disabled:opacity-50"
                  >
                    <Lock size={12} weight="duotone" /> Enable
                  </button>
                )}
              </div>
            </div>
          </section>

          {!s.all_required_accepted && (
            <div
              role="status"
              className="mb-5 flex items-start gap-2 rounded-md border border-amber-300 dark:border-amber-800/60 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-900 dark:text-amber-200"
            >
              <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
              <div>
                <strong className="font-medium">
                  {s.missing_required.length} required{" "}
                  {s.missing_required.length === 1 ? "agreement" : "agreements"}{" "}
                  pending acceptance:
                </strong>{" "}
                {s.missing_required.join(", ")}.
              </div>
            </div>
          )}

          <ul className="space-y-3">
            {s.agreements.map((a) => {
              const body = bodyById.get(a.id);
              const isOpen = expanded === a.id;
              return (
                <li
                  key={a.id}
                  className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                          {a.title}
                        </h3>
                        {a.required && (
                          <span className="rounded-full bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 px-2 py-0.5 text-[10px] uppercase tracking-wide">
                            required
                          </span>
                        )}
                        {a.accepted && !a.stale && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-200 px-2 py-0.5 text-[11px]">
                            <CheckCircle size={11} weight="duotone" /> accepted
                          </span>
                        )}
                        {a.stale && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-200 px-2 py-0.5 text-[11px]">
                            <Clock size={11} weight="duotone" /> needs reaccept
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                        {a.summary}
                      </p>
                      <p className="mt-2 text-[11px] font-mono text-neutral-500 dark:text-neutral-400">
                        version {a.current_version}
                        {a.latest_acceptance && (
                          <>
                            {" \u00b7 last accepted "}
                            {fmt(a.latest_acceptance.accepted_at)} by{" "}
                            <span className="text-neutral-700 dark:text-neutral-300">
                              {a.latest_acceptance.accepted_by}
                            </span>
                            {a.latest_acceptance.accepted_ip && (
                              <> from {a.latest_acceptance.accepted_ip}</>
                            )}
                          </>
                        )}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <button
                        type="button"
                        disabled={busy === a.id || (a.accepted && !a.stale)}
                        onClick={() => accept(a.id, a.current_version, a.title)}
                        className="inline-flex items-center gap-1 rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 px-3 py-1.5 text-xs disabled:opacity-50"
                      >
                        {a.accepted && !a.stale
                          ? "Up to date"
                          : a.stale
                            ? "Re-accept current version"
                            : "Accept current version"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : a.id)}
                        aria-expanded={isOpen}
                        className="inline-flex items-center gap-1 rounded-md border border-neutral-200 dark:border-neutral-800 px-2.5 py-1 text-[11px] text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-900"
                      >
                        <ClipboardText size={11} weight="duotone" />
                        {isOpen ? "Hide text" : "Read text"}
                      </button>
                    </div>
                  </div>
                  {isOpen && body && (
                    <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900 p-3 text-[12px] leading-5 text-neutral-800 dark:text-neutral-200">
                      {body}
                    </pre>
                  )}
                </li>
              );
            })}
          </ul>

          <section className="mt-8">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-900 dark:text-neutral-100">
              <ClipboardText size={16} weight="duotone" /> Acceptance ledger
            </h2>
            {!l || l.entries.length === 0 ? (
              <div className="rounded-md border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-6 text-sm text-neutral-500 dark:text-neutral-400">
                No acceptances recorded for this workspace yet.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950">
                <table className="min-w-full text-xs">
                  <thead className="bg-neutral-50 dark:bg-neutral-900 text-neutral-500 dark:text-neutral-400">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">When</th>
                      <th className="px-3 py-2 text-left font-medium">
                        Agreement
                      </th>
                      <th className="px-3 py-2 text-left font-medium">
                        Version
                      </th>
                      <th className="px-3 py-2 text-left font-medium">By</th>
                      <th className="px-3 py-2 text-left font-medium">IP</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                    {l.entries.map((e) => (
                      <tr key={e.id}>
                        <td className="px-3 py-2 tabular-nums text-neutral-700 dark:text-neutral-300">
                          {fmt(e.accepted_at)}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {e.agreement_id}
                        </td>
                        <td className="px-3 py-2 font-mono text-neutral-500 dark:text-neutral-400">
                          {e.version.slice(0, 12)}
                        </td>
                        <td className="px-3 py-2">{e.accepted_by}</td>
                        <td className="px-3 py-2 font-mono text-neutral-500 dark:text-neutral-400">
                          {e.accepted_ip ?? "\u2014"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
