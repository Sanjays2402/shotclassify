"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  UsersThree,
  ShieldCheck,
  ShieldWarning,
  CheckCircle,
  XCircle,
  Clock,
  UserCircle,
  Key,
  ArrowsClockwise,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Policy = {
  tenant_id: string;
  enabled: boolean;
  protected_scopes: string[];
  request_ttl_hours: number;
};

type IssuanceRequest = {
  id: string;
  requested_by: string;
  label: string;
  scopes: string[];
  ttl_days: number | null;
  owner_email: string | null;
  justification: string;
  status: string;
  created_at: string;
  expires_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  minted_key_id: string | null;
};

type QueueResponse = {
  tenant_id: string;
  policy_enabled: boolean;
  protected_scopes: string[];
  requests: IssuanceRequest[];
};

type ApiError = Error & { status?: number };

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function StatusPill({ s }: { s: string }) {
  const tone =
    s === "pending"
      ? "bg-amber-50 text-amber-900 ring-amber-200"
      : s === "approved"
        ? "bg-emerald-50 text-emerald-900 ring-emerald-200"
        : s === "denied" || s === "expired" || s === "cancelled"
          ? "bg-zinc-100 text-zinc-700 ring-zinc-200"
          : "bg-zinc-100 text-zinc-700 ring-zinc-200";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tone}`}
    >
      {s}
    </span>
  );
}

export default function DualControlPage() {
  const {
    data: policy,
    error: policyErr,
    isLoading: policyLoading,
    mutate: mutatePolicy,
  } = useSWR<Policy>("/api/settings/security/dual-control", fetcher, {
    revalidateOnFocus: false,
  });
  const { data: queue, mutate: mutateQueue } = useSWR<QueueResponse>(
    "/api/key-issuance-requests?include_recent=true&limit=50",
    fetcher,
    { revalidateOnFocus: false, refreshInterval: 15000 },
  );

  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<
    { kind: "ok" | "err"; msg: string } | null
  >(null);
  const [decisionNote, setDecisionNote] = useState<Record<string, string>>({});

  const status = policyErr as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const togglePolicy = async (next: boolean) => {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/dual-control", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      await mutatePolicy();
      setFlash({
        kind: "ok",
        msg: next
          ? "Two-person rule is on. New admin keys require peer approval."
          : "Two-person rule is off. Admins can mint keys without a second reviewer.",
      });
    } catch (err) {
      setFlash({ kind: "err", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const decide = async (id: string, action: "approve" | "deny") => {
    if (
      action === "approve" &&
      !confirm(
        "Approve this request and mint the key now? You will see the plaintext token exactly once and are responsible for handing it back to the requester through your credential channel.",
      )
    ) {
      return;
    }
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch(`/api/key-issuance-requests/${id}/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ note: decisionNote[id] ?? "" }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      await mutateQueue();
      if (action === "approve" && body.token) {
        setFlash({
          kind: "ok",
          msg: `Key minted. Token (shown once): ${body.token}`,
        });
      } else {
        setFlash({
          kind: "ok",
          msg: action === "approve" ? "Approved." : "Denied.",
        });
      }
    } catch (err) {
      setFlash({ kind: "err", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (unauth) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-xl font-semibold">Sign in required</h1>
        <p className="mt-2 text-sm text-zinc-600">
          Sign in with an admin account to manage the two-person rule.
        </p>
      </main>
    );
  }
  if (forbidden) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-xl font-semibold">Admin only</h1>
        <p className="mt-2 text-sm text-zinc-600">
          You need the workspace admin role to view this page.
        </p>
      </main>
    );
  }

  const pending = (queue?.requests ?? []).filter(
    (r) => r.status === "pending",
  );
  const recent = (queue?.requests ?? []).filter(
    (r) => r.status !== "pending",
  );

  return (
    <main className="mx-auto max-w-4xl px-4 py-8 sm:py-10">
      <header className="flex items-start gap-3">
        <UsersThree
          weight="duotone"
          className="mt-1 h-7 w-7 text-indigo-600"
          aria-hidden
        />
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Two-person rule for API keys
          </h1>
          <p className="mt-1 text-sm text-zinc-600">
            Require a second admin to approve any new API key with the{" "}
            <span className="font-mono">admin</span> scope. Separates duties on
            high-privilege credentials so a single compromised admin account
            cannot mint a backdoor key. Maps to SOC2 CC6.1 and the SoD control
            in most bank security questionnaires.
          </p>
        </div>
      </header>

      <section className="mt-8 rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
        {policyLoading ? (
          <div className="h-16 animate-pulse rounded bg-zinc-100" />
        ) : (
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              {policy?.enabled ? (
                <ShieldCheck
                  weight="duotone"
                  className="h-6 w-6 text-emerald-600"
                  aria-hidden
                />
              ) : (
                <ShieldWarning
                  weight="duotone"
                  className="h-6 w-6 text-amber-600"
                  aria-hidden
                />
              )}
              <div>
                <div className="text-sm font-medium">
                  {policy?.enabled ? "On" : "Off"}
                </div>
                <div className="text-xs text-zinc-500">
                  Protected scopes:{" "}
                  <span className="font-mono">
                    {(policy?.protected_scopes ?? []).join(", ") || "none"}
                  </span>
                  {" · "}
                  Requests expire after {policy?.request_ttl_hours ?? 72}{" "}
                  hours.
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => togglePolicy(!policy?.enabled)}
              disabled={busy}
              className="inline-flex items-center justify-center rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {policy?.enabled ? "Turn off" : "Turn on"}
            </button>
          </div>
        )}
      </section>

      {flash && (
        <div
          role="status"
          className={`mt-4 rounded-md border px-3 py-2 text-sm ${
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-rose-200 bg-rose-50 text-rose-900"
          }`}
        >
          {flash.msg}
        </div>
      )}

      <section className="mt-10">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Pending approvals</h2>
          <button
            type="button"
            onClick={() => mutateQueue()}
            className="inline-flex items-center gap-1 text-xs text-zinc-600 hover:text-zinc-900"
          >
            <ArrowsClockwise className="h-3.5 w-3.5" aria-hidden />
            Refresh
          </button>
        </div>
        {!queue ? (
          <div className="mt-3 h-24 animate-pulse rounded bg-zinc-100" />
        ) : pending.length === 0 ? (
          <div className="mt-3 rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-8 text-center text-sm text-zinc-600">
            <Key
              weight="duotone"
              className="mx-auto mb-2 h-6 w-6 text-zinc-400"
              aria-hidden
            />
            No requests waiting for review.
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {pending.map((r) => (
              <li
                key={r.id}
                className="rounded-lg border border-amber-200 bg-amber-50/40 p-4"
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono text-zinc-700">{r.label}</span>
                  <StatusPill s={r.status} />
                  {r.scopes.map((s) => (
                    <span
                      key={s}
                      className="rounded bg-white px-1.5 py-0.5 font-mono text-xs text-zinc-700 ring-1 ring-zinc-200"
                    >
                      {s}
                    </span>
                  ))}
                </div>
                <div className="mt-2 grid grid-cols-1 gap-1 text-xs text-zinc-600 sm:grid-cols-2">
                  <div className="flex items-center gap-1">
                    <UserCircle className="h-3.5 w-3.5" aria-hidden />
                    Requested by{" "}
                    <span className="font-medium text-zinc-800">
                      {r.requested_by}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" aria-hidden />
                    Asked {fmtTime(r.created_at)} · expires{" "}
                    {fmtTime(r.expires_at)}
                  </div>
                  {r.owner_email && (
                    <div className="sm:col-span-2">
                      Accountable owner:{" "}
                      <span className="font-mono">{r.owner_email}</span>
                    </div>
                  )}
                </div>
                <p className="mt-3 rounded bg-white p-3 text-sm text-zinc-800 ring-1 ring-zinc-200">
                  {r.justification}
                </p>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
                  <label className="flex-1 text-xs text-zinc-600">
                    Decision note (optional)
                    <input
                      type="text"
                      value={decisionNote[r.id] ?? ""}
                      onChange={(e) =>
                        setDecisionNote((m) => ({
                          ...m,
                          [r.id]: e.target.value,
                        }))
                      }
                      placeholder="e.g. ticket SEC-1042, ack from requester"
                      className="mt-1 w-full rounded-md border border-zinc-300 px-2 py-1.5 text-sm shadow-sm focus:border-zinc-900 focus:outline-none focus:ring-1 focus:ring-zinc-900"
                    />
                  </label>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => decide(r.id, "deny")}
                      className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-800 shadow-sm hover:bg-zinc-50 disabled:opacity-60"
                    >
                      <XCircle className="h-4 w-4" aria-hidden />
                      Deny
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => decide(r.id, "approve")}
                      className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-500 disabled:opacity-60"
                    >
                      <CheckCircle className="h-4 w-4" aria-hidden />
                      Approve and mint
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-10">
        <h2 className="text-base font-semibold">Recent decisions</h2>
        {!queue ? (
          <div className="mt-3 h-16 animate-pulse rounded bg-zinc-100" />
        ) : recent.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">
            No decisions recorded yet.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-zinc-100 rounded-lg border border-zinc-200 bg-white">
            {recent.map((r) => (
              <li
                key={r.id}
                className="flex flex-col gap-1 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-zinc-700">{r.label}</span>
                  <StatusPill s={r.status} />
                  <span className="text-xs text-zinc-500">
                    {r.scopes.join(", ")}
                  </span>
                </div>
                <div className="text-xs text-zinc-500">
                  {r.decided_by ? `By ${r.decided_by}` : "No decision"} ·{" "}
                  {fmtTime(r.decided_at ?? r.expires_at)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
