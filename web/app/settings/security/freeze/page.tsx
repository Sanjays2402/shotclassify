"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  Snowflake,
  Warning,
  CheckCircle,
  Lock,
  LockOpen,
  Clock,
  UserCircle,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type FreezeState = {
  tenant_id: string;
  frozen: boolean;
  reason: string | null;
  engaged_at: string | null;
  engaged_by: string | null;
};

type ApiError = Error & { status?: number };

const REASON_MAX = 256;

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function FreezePage() {
  const { data, error, isLoading, mutate } = useSWR<FreezeState>(
    "/api/settings/security/freeze",
    fetcher,
    { revalidateOnFocus: false },
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<
    { kind: "ok" | "err"; msg: string } | null
  >(null);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const engage = async () => {
    const trimmed = reason.trim();
    if (!trimmed) {
      setFlash({ kind: "err", msg: "Reason is required." });
      return;
    }
    if (!confirm(
      "Engage emergency freeze? Every write to this workspace will be blocked until you lift it.",
    )) {
      return;
    }
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/freeze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reason: trimmed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body?.detail || body?.error || res.statusText;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      await mutate();
      setReason("");
      setFlash({ kind: "ok", msg: "Freeze engaged. Writes are now blocked." });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const lift = async () => {
    if (!confirm("Lift the freeze and allow writes again?")) return;
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/freeze", {
        method: "DELETE",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body?.detail || body?.error || res.statusText;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      await mutate();
      setFlash({ kind: "ok", msg: "Freeze lifted. Writes are allowed." });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:py-12">
      <header className="mb-8 flex items-start gap-3">
        <Snowflake weight="duotone" className="mt-1 h-7 w-7 text-sky-500" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Emergency freeze
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            One switch to halt every write to this workspace during a
            suspected incident. Reads, exports and the audit log keep
            working so investigators can still do their job.
          </p>
        </div>
      </header>

      {unauth && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-700 dark:text-amber-300">
          Sign in to manage emergency freeze.
        </div>
      )}
      {forbidden && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-700 dark:text-red-300">
          Admin role required.
        </div>
      )}

      {!unauth && !forbidden && isLoading && (
        <div className="space-y-3">
          <div className="h-24 animate-pulse rounded-md bg-neutral-200/60 dark:bg-neutral-800/60" />
          <div className="h-40 animate-pulse rounded-md bg-neutral-200/60 dark:bg-neutral-800/60" />
        </div>
      )}

      {data && (
        <>
          {data.frozen ? (
            <section
              role="status"
              aria-live="polite"
              className="mb-6 rounded-lg border border-red-500/40 bg-red-500/10 p-5"
            >
              <div className="flex items-start gap-3">
                <Lock weight="duotone" className="mt-0.5 h-6 w-6 text-red-600" />
                <div className="flex-1">
                  <h2 className="text-base font-semibold text-red-700 dark:text-red-300">
                    Workspace is frozen
                  </h2>
                  <p className="mt-1 text-sm text-red-700/90 dark:text-red-300/90">
                    Every write to <span className="font-mono">{data.tenant_id}</span> is rejected with HTTP 423 ``tenant_frozen`` until a workspace admin lifts the freeze.
                  </p>
                  {data.reason && (
                    <div className="mt-3 rounded border border-red-500/20 bg-white/40 p-3 text-sm text-neutral-800 dark:bg-black/20 dark:text-neutral-100">
                      <div className="text-xs uppercase tracking-wide text-neutral-500">
                        Reason
                      </div>
                      <div className="mt-0.5">{data.reason}</div>
                    </div>
                  )}
                  <dl className="mt-3 grid grid-cols-1 gap-2 text-sm text-neutral-700 sm:grid-cols-2 dark:text-neutral-200">
                    <div className="flex items-center gap-2">
                      <Clock weight="duotone" className="h-4 w-4 text-neutral-500" />
                      <span className="text-neutral-500">Engaged</span>
                      <span className="font-mono">{fmtTime(data.engaged_at)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <UserCircle weight="duotone" className="h-4 w-4 text-neutral-500" />
                      <span className="text-neutral-500">By</span>
                      <span className="font-mono">{data.engaged_by ?? "unknown"}</span>
                    </div>
                  </dl>
                </div>
              </div>
            </section>
          ) : (
            <section className="mb-6 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-5">
              <div className="flex items-start gap-3">
                <CheckCircle weight="duotone" className="mt-0.5 h-6 w-6 text-emerald-600" />
                <div>
                  <h2 className="text-base font-semibold text-emerald-700 dark:text-emerald-300">
                    Workspace is live
                  </h2>
                  <p className="mt-1 text-sm text-emerald-700/90 dark:text-emerald-300/90">
                    No freeze engaged for <span className="font-mono">{data.tenant_id}</span>. Use the form below only during a real or suspected incident.
                  </p>
                </div>
              </div>
            </section>
          )}

          {data.frozen ? (
            <div className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-950">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <LockOpen weight="duotone" className="h-4 w-4 text-neutral-500" />
                Lift freeze
              </h3>
              <p className="mt-1 text-sm text-neutral-500">
                Restores write access for every member of this workspace.
              </p>
              <button
                type="button"
                onClick={lift}
                disabled={busy}
                className="mt-4 inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
              >
                <LockOpen weight="duotone" className="h-4 w-4" />
                {busy ? "Lifting" : "Lift freeze"}
              </button>
            </div>
          ) : (
            <div className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-950">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Warning weight="duotone" className="h-4 w-4 text-amber-500" />
                Engage freeze
              </h3>
              <p className="mt-1 text-sm text-neutral-500">
                Blocks every POST, PUT, PATCH and DELETE on this workspace
                until an admin lifts it. Requires a written reason that
                will be shown to every blocked caller.
              </p>
              <label className="mt-4 block text-xs font-medium uppercase tracking-wide text-neutral-500">
                Reason
              </label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX))}
                rows={3}
                placeholder="Suspected leaked admin token, departing engineer, anomalous spike, etc."
                className="mt-1 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm shadow-inner focus:border-neutral-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-900"
              />
              <div className="mt-1 flex items-center justify-between text-xs text-neutral-500">
                <span>Required. Shown in the 423 error body.</span>
                <span>
                  {reason.length}/{REASON_MAX}
                </span>
              </div>
              <button
                type="button"
                onClick={engage}
                disabled={busy || !reason.trim()}
                className="mt-4 inline-flex items-center gap-2 rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                <Lock weight="duotone" className="h-4 w-4" />
                {busy ? "Engaging" : "Engage freeze"}
              </button>
            </div>
          )}

          {flash && (
            <div
              role="status"
              aria-live="polite"
              className={`mt-4 rounded-md border p-3 text-sm ${
                flash.kind === "ok"
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
              }`}
            >
              {flash.msg}
            </div>
          )}

          <p className="mt-8 text-xs text-neutral-500">
            Lifting and engaging require a fresh MFA step-up. Both
            actions are recorded in the audit log with actor, IP and
            request id.
          </p>
        </>
      )}
    </div>
  );
}
