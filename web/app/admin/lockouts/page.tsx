"use client";

// Workspace admin: brute-force authentication lockout console.
// Lists active and historical lockouts for the caller's tenant, lets an
// admin clear a single lockout (re-enable that source IP), and edit the
// per-tenant threshold/window/cooldown policy. All writes go through
// proxy routes that forward the session cookie or API key, and the
// FastAPI side enforces admin role + MFA step-up on mutations.

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ShieldWarning,
  ShieldCheck,
  LockKey,
  LockKeyOpen,
  ArrowClockwise,
  WarningCircle,
  CheckCircle,
  ListMagnifyingGlass,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Lockout = {
  id: number;
  ip: string;
  reason: string;
  failures_in_window: number;
  created_at: string;
  locked_until: string;
  cleared_at: string | null;
  cleared_by: string | null;
  active: boolean;
};

type Policy = {
  tenant_id: string;
  threshold: number;
  window_minutes: number;
  cooldown_minutes: number;
  enabled: boolean;
};

type Bounds = {
  threshold_min: number;
  threshold_max: number;
  window_min_minutes: number;
  window_max_minutes: number;
  cooldown_min_minutes: number;
  cooldown_max_minutes: number;
};

type FailureRow = { id: number; ip: string; kind: string; ts: string };

type AdminPayload = {
  tenant_id: string;
  policy: Policy & { bounds: Bounds };
  bounds: Bounds;
  lockouts: Lockout[];
  recent_failures: FailureRow[];
};

function fmt(ts: string | null): string {
  if (!ts) return "never";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

function Skeleton() {
  return (
    <div className="space-y-2" aria-busy="true">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-10 rounded bg-neutral-200 dark:bg-neutral-800 animate-pulse"
        />
      ))}
    </div>
  );
}

export default function LockoutsPage() {
  const { data, error, mutate, isLoading } = useSWR<AdminPayload>(
    "/api/admin/lockouts",
    fetcher,
    { refreshInterval: 15_000 },
  );

  const [threshold, setThreshold] = useState<string>("");
  const [windowMin, setWindowMin] = useState<string>("");
  const [cooldown, setCooldown] = useState<string>("");
  const [mfa, setMfa] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [policyMsg, setPolicyMsg] = useState<string | null>(null);
  const [policyErr, setPolicyErr] = useState<string | null>(null);
  const [clearingId, setClearingId] = useState<number | null>(null);
  const [clearErr, setClearErr] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setThreshold(data.policy.enabled ? String(data.policy.threshold) : "");
    setWindowMin(
      data.policy.enabled ? String(data.policy.window_minutes) : "",
    );
    setCooldown(
      data.policy.enabled ? String(data.policy.cooldown_minutes) : "",
    );
  }, [data?.policy.enabled, data?.policy.threshold, data?.policy.window_minutes, data?.policy.cooldown_minutes]);

  const bounds = data?.bounds;

  const active = useMemo(
    () => (data?.lockouts ?? []).filter((r) => r.active),
    [data],
  );
  const historical = useMemo(
    () => (data?.lockouts ?? []).filter((r) => !r.active),
    [data],
  );

  async function savePolicy(clear = false) {
    setSaving(true);
    setPolicyErr(null);
    setPolicyMsg(null);
    try {
      const body = clear
        ? { threshold: null, window_minutes: null, cooldown_minutes: null }
        : {
            threshold: Number(threshold),
            window_minutes: Number(windowMin),
            cooldown_minutes: Number(cooldown),
          };
      const csrf = await getCsrf();
      const headers: Record<string, string> = { "content-type": "application/json" };
      if (mfa) headers["x-mfa-otp"] = mfa;
      if (csrf) headers["x-csrf-token"] = csrf;
      const r = await fetch("/api/settings/security/auth-lockout", {
        method: "PUT",
        headers,
        body: JSON.stringify(body),
        credentials: "same-origin",
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || `${r.status} ${r.statusText}`);
      }
      setPolicyMsg(clear ? "Policy cleared." : "Policy saved.");
      setMfa("");
      mutate();
    } catch (e: any) {
      setPolicyErr(e?.message ?? String(e));
    } finally {
      setSaving(false);
    }
  }

  async function clearLockout(id: number) {
    setClearingId(id);
    setClearErr(null);
    try {
      const csrf = await getCsrf();
      const headers: Record<string, string> = {};
      if (mfa) headers["x-mfa-otp"] = mfa;
      if (csrf) headers["x-csrf-token"] = csrf;
      const r = await fetch(`/api/admin/lockouts/${id}`, {
        method: "DELETE",
        headers,
        credentials: "same-origin",
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || `${r.status} ${r.statusText}`);
      }
      mutate();
    } catch (e: any) {
      setClearErr(e?.message ?? String(e));
    } finally {
      setClearingId(null);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:py-10 space-y-8">
      <header className="space-y-2">
        <div className="flex items-center gap-2 text-neutral-500 dark:text-neutral-400 text-sm">
          <ShieldWarning size={18} weight="duotone" />
          <span>Security / Brute-force lockouts</span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Authentication lockouts
        </h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400 max-w-2xl">
          When a source IP fails too many credential checks against this
          workspace inside the configured window, that IP is locked out for
          the cooldown and every request returns HTTP 423. Lockouts are
          per workspace and per IP, so a noisy attacker against one tenant
          cannot affect another tenant on the same shared deployment.
        </p>
      </header>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <LockKey size={20} weight="duotone" />
            <h2 className="text-lg font-medium">Policy</h2>
          </div>
          <button
            type="button"
            onClick={() => mutate()}
            className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            <ArrowClockwise size={16} weight="duotone" /> refresh
          </button>
        </div>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          {data?.policy.enabled ? (
            <span className="text-emerald-600 dark:text-emerald-400 inline-flex items-center gap-1">
              <ShieldCheck size={16} weight="duotone" /> Active for tenant
              {" "}<code className="text-xs">{data.tenant_id}</code>
            </span>
          ) : (
            <span className="text-amber-600 dark:text-amber-400 inline-flex items-center gap-1">
              <WarningCircle size={16} weight="duotone" /> Disabled. No
              lockouts will be created until you set all three values below.
            </span>
          )}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <label className="block text-sm">
            <span className="text-neutral-600 dark:text-neutral-400">
              Threshold (failures)
            </span>
            <input
              type="number"
              inputMode="numeric"
              min={bounds?.threshold_min}
              max={bounds?.threshold_max}
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              placeholder={bounds ? `${bounds.threshold_min}-${bounds.threshold_max}` : ""}
              className="mt-1 w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
          <label className="block text-sm">
            <span className="text-neutral-600 dark:text-neutral-400">
              Window (minutes)
            </span>
            <input
              type="number"
              inputMode="numeric"
              min={bounds?.window_min_minutes}
              max={bounds?.window_max_minutes}
              value={windowMin}
              onChange={(e) => setWindowMin(e.target.value)}
              placeholder={bounds ? `${bounds.window_min_minutes}-${bounds.window_max_minutes}` : ""}
              className="mt-1 w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
          <label className="block text-sm">
            <span className="text-neutral-600 dark:text-neutral-400">
              Cooldown (minutes)
            </span>
            <input
              type="number"
              inputMode="numeric"
              min={bounds?.cooldown_min_minutes}
              max={bounds?.cooldown_max_minutes}
              value={cooldown}
              onChange={(e) => setCooldown(e.target.value)}
              placeholder={bounds ? `${bounds.cooldown_min_minutes}-${bounds.cooldown_max_minutes}` : ""}
              className="mt-1 w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
        </div>
        <label className="block text-sm">
          <span className="text-neutral-600 dark:text-neutral-400">
            MFA code (required for save and clear)
          </span>
          <input
            type="text"
            inputMode="numeric"
            value={mfa}
            onChange={(e) => setMfa(e.target.value)}
            placeholder="6-digit TOTP"
            className="mt-1 w-full sm:w-48 rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </label>
        {policyErr && (
          <p className="text-sm text-red-600 dark:text-red-400 inline-flex items-center gap-1">
            <WarningCircle size={16} weight="duotone" /> {policyErr}
          </p>
        )}
        {policyMsg && (
          <p className="text-sm text-emerald-600 dark:text-emerald-400 inline-flex items-center gap-1">
            <CheckCircle size={16} weight="duotone" /> {policyMsg}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => savePolicy(false)}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-md bg-neutral-900 dark:bg-neutral-100 text-neutral-50 dark:text-neutral-900 px-3 py-2 text-sm font-medium disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {saving ? "Saving" : "Save policy"}
          </button>
          <button
            type="button"
            onClick={() => savePolicy(true)}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-md border border-neutral-300 dark:border-neutral-700 px-3 py-2 text-sm disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Clear policy
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-5 space-y-3">
        <div className="flex items-center gap-2">
          <LockKey size={20} weight="duotone" />
          <h2 className="text-lg font-medium">Active lockouts</h2>
          <span className="text-xs text-neutral-500">({active.length})</span>
        </div>
        {isLoading && <Skeleton />}
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400 inline-flex items-center gap-1">
            <WarningCircle size={16} weight="duotone" /> {String((error as Error).message || error)}
          </p>
        )}
        {!isLoading && !error && active.length === 0 && (
          <p className="text-sm text-neutral-500 dark:text-neutral-400 inline-flex items-center gap-1">
            <ShieldCheck size={16} weight="duotone" /> No active lockouts.
            Every source IP can authenticate against this workspace.
          </p>
        )}
        {clearErr && (
          <p className="text-sm text-red-600 dark:text-red-400 inline-flex items-center gap-1">
            <WarningCircle size={16} weight="duotone" /> {clearErr}
          </p>
        )}
        {active.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-neutral-500 dark:text-neutral-400">
                <tr>
                  <th className="py-2 pr-3">Source IP</th>
                  <th className="py-2 pr-3">Reason</th>
                  <th className="py-2 pr-3">Failures</th>
                  <th className="py-2 pr-3">Locked until</th>
                  <th className="py-2 pr-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {active.map((r) => (
                  <tr key={r.id} className="border-t border-neutral-100 dark:border-neutral-800">
                    <td className="py-2 pr-3 font-mono text-xs">{r.ip}</td>
                    <td className="py-2 pr-3">{r.reason}</td>
                    <td className="py-2 pr-3">{r.failures_in_window}</td>
                    <td className="py-2 pr-3">{fmt(r.locked_until)}</td>
                    <td className="py-2 pr-3">
                      <button
                        type="button"
                        onClick={() => clearLockout(r.id)}
                        disabled={clearingId === r.id}
                        className="inline-flex items-center gap-1 rounded-md border border-neutral-300 dark:border-neutral-700 px-2 py-1 text-xs disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <LockKeyOpen size={14} weight="duotone" />
                        {clearingId === r.id ? "Clearing" : "Clear"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-5 space-y-3">
        <div className="flex items-center gap-2">
          <ListMagnifyingGlass size={20} weight="duotone" />
          <h2 className="text-lg font-medium">Recent history</h2>
          <span className="text-xs text-neutral-500">({historical.length})</span>
        </div>
        {historical.length === 0 ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            No expired or cleared lockouts on file yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-neutral-500 dark:text-neutral-400">
                <tr>
                  <th className="py-2 pr-3">Source IP</th>
                  <th className="py-2 pr-3">Reason</th>
                  <th className="py-2 pr-3">Created</th>
                  <th className="py-2 pr-3">Locked until</th>
                  <th className="py-2 pr-3">Cleared by</th>
                </tr>
              </thead>
              <tbody>
                {historical.map((r) => (
                  <tr key={r.id} className="border-t border-neutral-100 dark:border-neutral-800">
                    <td className="py-2 pr-3 font-mono text-xs">{r.ip}</td>
                    <td className="py-2 pr-3">{r.reason}</td>
                    <td className="py-2 pr-3">{fmt(r.created_at)}</td>
                    <td className="py-2 pr-3">{fmt(r.locked_until)}</td>
                    <td className="py-2 pr-3">{r.cleared_by ?? "expired"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

async function getCsrf(): Promise<string | null> {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|; )sc_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}
