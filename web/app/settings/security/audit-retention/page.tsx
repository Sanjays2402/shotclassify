"use client";

// Per-tenant audit-log retention policy. Independent of the
// classifications retention window because enterprise customers
// negotiate these two clauses separately: short GDPR-style audit
// windows (90 to 365 days) for data minimisation vs long SOC2/HIPAA
// windows (>= 365 days) for forensics. Lowering the window does not
// retroactively purge; the next scheduled or manual run does that.

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ClockCounterClockwise,
  FloppyDisk,
  Warning,
  CheckCircle,
  Lock,
  Broom,
  ShieldWarning,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type PolicyResponse = {
  tenant_id: string;
  audit_retention_days: number | null;
  enabled: boolean;
  max_days: number;
};

type RunResponse = {
  tenant_id: string;
  audit_retention_days: number;
  cutoff: string;
  removed: number;
  held?: boolean;
};

type ApiError = Error & { status?: number };

const PRESETS: { label: string; days: number | null; hint: string }[] = [
  { label: "Keep forever", days: null, hint: "Default. No automatic deletion." },
  { label: "90 days", days: 90, hint: "GDPR-aligned minimisation." },
  { label: "1 year", days: 365, hint: "Common SaaS contract default." },
  { label: "3 years", days: 1095, hint: "SOC 2 forensics window." },
  { label: "7 years", days: 2555, hint: "HIPAA / financial records." },
];

function describeDays(d: number | null): string {
  if (d === null || d <= 0) return "kept indefinitely";
  if (d % 365 === 0) {
    const y = d / 365;
    return `${y} year${y === 1 ? "" : "s"}`;
  }
  return `${d} day${d === 1 ? "" : "s"}`;
}

export default function AuditRetentionPage() {
  const { data, error, isLoading, mutate } = useSWR<PolicyResponse>(
    "/api/settings/security/audit-retention",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [draftEnabled, setDraftEnabled] = useState(false);
  const [draftDays, setDraftDays] = useState<string>("365");
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);

  useEffect(() => {
    if (!data) return;
    setDraftEnabled(data.enabled);
    if (data.audit_retention_days && data.audit_retention_days > 0) {
      setDraftDays(String(data.audit_retention_days));
    }
  }, [data]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;
  const maxDays = data?.max_days ?? 3650;

  const parsedDays = useMemo(() => {
    const n = Number(draftDays);
    if (!Number.isFinite(n) || !Number.isInteger(n)) return null;
    if (n < 1 || n > maxDays) return null;
    return n;
  }, [draftDays, maxDays]);

  const dirty = useMemo(() => {
    if (!data) return false;
    if (draftEnabled !== data.enabled) return true;
    if (draftEnabled && parsedDays !== data.audit_retention_days) return true;
    return false;
  }, [data, draftEnabled, parsedDays]);

  const canSave = !busy && dirty && (!draftEnabled || parsedDays !== null);

  async function save() {
    setBusy(true);
    setFlash(null);
    try {
      const value = draftEnabled ? parsedDays : null;
      const res = await fetch("/api/settings/security/audit-retention", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ audit_retention_days: value }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail ?? body.error ?? `HTTP ${res.status}`);
      }
      await mutate();
      setFlash({
        kind: "ok",
        msg: value
          ? `Policy saved. Audit rows older than ${describeDays(value)} are eligible for the next purge.`
          : "Policy cleared. Audit log is now kept indefinitely.",
      });
    } catch (e) {
      setFlash({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    if (!data?.enabled) return;
    if (
      !confirm(
        "Run an audit-log purge now? Rows older than the policy window in this workspace will be hard-deleted. This breaks the audit hash chain for the deleted window by design and is itself recorded as an audit entry.",
      )
    ) {
      return;
    }
    setRunning(true);
    setFlash(null);
    setLastRun(null);
    try {
      const res = await fetch("/api/settings/security/audit-retention/run", {
        method: "POST",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail ?? body.error ?? `HTTP ${res.status}`);
      }
      setLastRun(body as RunResponse);
      setFlash({
        kind: "ok",
        msg: body.held
          ? "Workspace is on a legal hold. No audit rows were removed."
          : `Purge complete. ${body.removed} audit row${body.removed === 1 ? "" : "s"} removed.`,
      });
    } catch (e) {
      setFlash({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setRunning(false);
    }
  }

  function applyPreset(days: number | null) {
    if (days === null) {
      setDraftEnabled(false);
    } else {
      setDraftEnabled(true);
      setDraftDays(String(days));
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:py-10">
      <header className="mb-6 flex items-start gap-3">
        <ClockCounterClockwise size={28} weight="duotone" className="mt-1 shrink-0" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Audit log retention
          </h1>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Choose how long this workspace keeps audit rows. The default keeps
            them forever. Set a window for GDPR-aligned minimisation, or
            leave it off for full SOC 2 forensics. The classifications
            retention policy is separate and lives on the data settings page.
          </p>
        </div>
      </header>

      {unauth && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <div className="flex items-center gap-2">
            <Lock size={16} weight="duotone" />
            <span>Sign in to manage security settings.</span>
          </div>
        </div>
      )}

      {forbidden && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <div className="flex items-center gap-2">
            <Warning size={16} weight="duotone" />
            <span>You need the admin role to manage audit retention.</span>
          </div>
        </div>
      )}

      {!unauth && !forbidden && (
        <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-950 sm:p-6">
          {isLoading && !data ? (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-9 w-2/3 animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
              <div className="h-9 w-full animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
              <div className="h-9 w-1/2 animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
            </div>
          ) : (
            <>
              <div className="mb-5 flex items-center justify-between gap-4 rounded-md border border-neutral-200 px-4 py-3 dark:border-neutral-800">
                <div>
                  <div className="text-sm font-medium">Current policy</div>
                  <div className="text-xs text-neutral-500 dark:text-neutral-400">
                    {data && data.enabled
                      ? `Audit rows older than ${describeDays(data.audit_retention_days)} are eligible for purge.`
                      : "No window. Audit rows are kept indefinitely."}
                  </div>
                </div>
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${
                    data?.enabled
                      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                      : "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"
                  }`}
                >
                  {data?.enabled ? "Active" : "Off"}
                </span>
              </div>

              <fieldset className="space-y-3">
                <label className="flex items-start gap-3">
                  <input
                    type="radio"
                    name="audit-retention-mode"
                    className="mt-1"
                    checked={!draftEnabled}
                    onChange={() => setDraftEnabled(false)}
                  />
                  <div>
                    <div className="text-sm font-medium">Keep audit log forever</div>
                    <div className="text-xs text-neutral-500 dark:text-neutral-400">
                      Default. Recommended when you need SOC 2 or HIPAA-style
                      forensics over multi-year windows.
                    </div>
                  </div>
                </label>

                <label className="flex items-start gap-3">
                  <input
                    type="radio"
                    name="audit-retention-mode"
                    className="mt-1"
                    checked={draftEnabled}
                    onChange={() => setDraftEnabled(true)}
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium">
                      Delete audit rows older than
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <input
                        type="number"
                        min={1}
                        max={maxDays}
                        step={1}
                        inputMode="numeric"
                        disabled={!draftEnabled}
                        value={draftDays}
                        onChange={(e) => setDraftDays(e.target.value)}
                        aria-label="Audit retention days"
                        className="h-9 w-28 rounded-md border border-neutral-300 bg-white px-3 text-sm outline-none transition focus:border-neutral-500 focus:ring-2 focus:ring-neutral-300 disabled:opacity-50 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-500 dark:focus:ring-neutral-700"
                      />
                      <span className="text-sm text-neutral-600 dark:text-neutral-400">
                        days
                      </span>
                    </div>
                    {draftEnabled && parsedDays === null && (
                      <div className="mt-1 text-xs text-red-600 dark:text-red-300">
                        Enter an integer between 1 and {maxDays}.
                      </div>
                    )}
                  </div>
                </label>
              </fieldset>

              <div className="mt-4 flex flex-wrap gap-2">
                {PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => applyPreset(p.days)}
                    title={p.hint}
                    className="rounded-full border border-neutral-300 px-3 py-1 text-xs font-medium text-neutral-700 transition hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-900"
                  >
                    {p.label}
                  </button>
                ))}
              </div>

              <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
                <button
                  type="button"
                  onClick={runNow}
                  disabled={!data?.enabled || running}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-neutral-300 px-4 text-sm font-medium transition hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
                >
                  <Broom size={16} weight="duotone" />
                  {running ? "Running" : "Run purge now"}
                </button>
                <button
                  type="button"
                  onClick={save}
                  disabled={!canSave}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                >
                  <FloppyDisk size={16} weight="duotone" />
                  {busy ? "Saving" : "Save policy"}
                </button>
              </div>

              {flash && (
                <div
                  role="status"
                  className={`mt-4 flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
                    flash.kind === "ok"
                      ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                      : "border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
                  }`}
                >
                  {flash.kind === "ok" ? (
                    <CheckCircle size={16} weight="duotone" className="mt-0.5 shrink-0" />
                  ) : (
                    <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
                  )}
                  <span>{flash.msg}</span>
                </div>
              )}

              {lastRun && (
                <dl className="mt-4 grid grid-cols-2 gap-3 rounded-md border border-neutral-200 bg-neutral-50 px-4 py-3 text-xs dark:border-neutral-800 dark:bg-neutral-900 sm:grid-cols-4">
                  <div>
                    <dt className="text-neutral-500 dark:text-neutral-400">Removed</dt>
                    <dd className="mt-0.5 font-mono text-sm">{lastRun.removed}</dd>
                  </div>
                  <div>
                    <dt className="text-neutral-500 dark:text-neutral-400">Window</dt>
                    <dd className="mt-0.5 font-mono text-sm">
                      {lastRun.audit_retention_days}d
                    </dd>
                  </div>
                  <div className="col-span-2 sm:col-span-2">
                    <dt className="text-neutral-500 dark:text-neutral-400">Cutoff</dt>
                    <dd className="mt-0.5 break-all font-mono text-[11px]">
                      {lastRun.cutoff}
                    </dd>
                  </div>
                </dl>
              )}

              <div className="mt-5 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
                <ShieldWarning size={14} weight="duotone" className="mt-0.5 shrink-0" />
                <span>
                  Purging audit rows breaks the per-tenant audit hash chain for
                  the deleted window by design. The purge itself is recorded as
                  an audit entry, so the chain verifier reports the gap as an
                  attributable, disclosed event rather than tampering.
                </span>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
