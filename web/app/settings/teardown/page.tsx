"use client";

import { useEffect, useState } from "react";
import {
  Clock,
  Prohibit,
  ShieldWarning,
  Skull,
  Timer,
  Warning,
} from "@phosphor-icons/react/dist/ssr";

type TeardownState = {
  tenant_id: string;
  scheduled: boolean;
  scheduled_at: string | null;
  scheduled_by: string | null;
  execute_after: string | null;
  reason: string | null;
  status: "none" | "scheduled" | "executed";
  ready_to_execute: boolean;
};

type ExecuteResult = {
  tenant_id: string;
  executed: boolean;
  schedule: TeardownState;
  deleted: Record<string, number>;
};

type Flash = { kind: "ok" | "err"; msg: string };

function readMfaOtp(): string | null {
  if (typeof window === "undefined") return null;
  const otp = window.prompt(
    "Enter your 6 digit MFA code to authorize this action.",
  );
  if (!otp) return null;
  const cleaned = otp.trim();
  if (!/^\d{6}$/.test(cleaned)) {
    window.alert("MFA code must be 6 digits.");
    return null;
  }
  return cleaned;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function countdown(iso: string | null): string {
  if (!iso) return "";
  const target = new Date(iso).getTime();
  const now = Date.now();
  const diff = target - now;
  if (diff <= 0) return "ready now";
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  if (h >= 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h remaining`;
  }
  return `${h}h ${m}m remaining`;
}

export default function WorkspaceTeardownPage() {
  const [state, setState] = useState<TeardownState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<
    "schedule" | "cancel" | "execute" | null
  >(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [confirm, setConfirm] = useState("");
  const [cooloff, setCooloff] = useState(168);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<ExecuteResult | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch("/v1/workspace/teardown", {
        credentials: "include",
      });
      if (!r.ok) throw new Error(await r.text());
      setState((await r.json()) as TeardownState);
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const id = setInterval(() => setState((s) => (s ? { ...s } : s)), 60_000);
    return () => clearInterval(id);
  }, []);

  const tenant = state?.tenant_id ?? "";

  const doSchedule = async () => {
    if (!tenant) {
      setFlash({ kind: "err", msg: "No tenant context resolved yet." });
      return;
    }
    if (confirm !== tenant) {
      setFlash({
        kind: "err",
        msg: `Type the workspace id exactly: ${tenant}`,
      });
      return;
    }
    const otp = readMfaOtp();
    if (!otp) return;
    setBusy("schedule");
    setFlash(null);
    try {
      const r = await fetch("/v1/workspace/teardown", {
        method: "POST",
        credentials: "include",
        headers: {
          "content-type": "application/json",
          "x-mfa-otp": otp,
        },
        body: JSON.stringify({
          confirm,
          cooloff_hours: cooloff,
          reason: reason || null,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      setState((await r.json()) as TeardownState);
      setConfirm("");
      setReason("");
      setFlash({
        kind: "ok",
        msg: "Teardown scheduled. Cooling-off period started.",
      });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const doCancel = async () => {
    const otp = readMfaOtp();
    if (!otp) return;
    setBusy("cancel");
    setFlash(null);
    try {
      const r = await fetch("/v1/workspace/teardown", {
        method: "DELETE",
        credentials: "include",
        headers: { "x-mfa-otp": otp },
      });
      if (!r.ok) throw new Error(await r.text());
      await load();
      setFlash({ kind: "ok", msg: "Scheduled teardown cancelled." });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const doExecute = async () => {
    if (!tenant) return;
    const phrase = window.prompt(
      `This permanently deletes workspace "${tenant}". Type the workspace id to confirm:`,
    );
    if (phrase !== tenant) {
      setFlash({
        kind: "err",
        msg: "Confirmation did not match. Nothing was deleted.",
      });
      return;
    }
    const otp = readMfaOtp();
    if (!otp) return;
    setBusy("execute");
    setFlash(null);
    try {
      const r = await fetch(
        `/v1/workspace/teardown/execute?confirm=${encodeURIComponent(tenant)}`,
        {
          method: "POST",
          credentials: "include",
          headers: { "x-mfa-otp": otp },
        },
      );
      if (!r.ok) throw new Error(await r.text());
      const body = (await r.json()) as ExecuteResult;
      setResult(body);
      await load();
      setFlash({ kind: "ok", msg: "Workspace teardown executed." });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:py-14">
      <header className="mb-8">
        <div className="flex items-center gap-3">
          <Skull
            weight="duotone"
            className="h-8 w-8 text-red-600 dark:text-red-400"
          />
          <h1 className="text-2xl font-semibold tracking-tight">
            Workspace teardown
          </h1>
        </div>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Schedule a full hard delete of this workspace. There is a mandatory
          cooling-off period before execute is allowed. Per-user exports and
          partial purges live on the Data page.
        </p>
      </header>

      {flash && (
        <div
          role="status"
          className={`mb-6 rounded-md border px-4 py-3 text-sm ${
            flash.kind === "ok"
              ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-100"
              : "border-red-300 bg-red-50 text-red-900 dark:border-red-700 dark:bg-red-950 dark:text-red-100"
          }`}
        >
          {flash.msg}
        </div>
      )}

      <section className="rounded-lg border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-4 flex items-center gap-2 text-sm font-medium">
          <Clock weight="duotone" className="h-5 w-5 text-zinc-500" />
          Current schedule
        </div>
        {loading ? (
          <div className="space-y-2">
            <div className="h-4 w-1/2 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
            <div className="h-4 w-1/3 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
          </div>
        ) : state?.scheduled ? (
          <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-zinc-500">Workspace</dt>
              <dd className="font-mono">{state.tenant_id}</dd>
            </div>
            <div>
              <dt className="text-zinc-500">Scheduled by</dt>
              <dd className="font-mono">{state.scheduled_by ?? "unknown"}</dd>
            </div>
            <div>
              <dt className="text-zinc-500">Scheduled at</dt>
              <dd>{fmtDate(state.scheduled_at)}</dd>
            </div>
            <div>
              <dt className="text-zinc-500">Execute after</dt>
              <dd>
                {fmtDate(state.execute_after)}{" "}
                <span className="text-zinc-500">
                  ({countdown(state.execute_after)})
                </span>
              </dd>
            </div>
            {state.reason && (
              <div className="sm:col-span-2">
                <dt className="text-zinc-500">Reason</dt>
                <dd>{state.reason}</dd>
              </div>
            )}
          </dl>
        ) : (
          <p className="text-sm text-zinc-500">
            No teardown is currently scheduled for this workspace.
          </p>
        )}

        {state?.scheduled && (
          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <button
              type="button"
              onClick={doCancel}
              disabled={busy !== null}
              className="inline-flex items-center justify-center gap-2 rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              <Prohibit weight="duotone" className="h-4 w-4" />
              Cancel teardown
            </button>
            <button
              type="button"
              onClick={doExecute}
              disabled={busy !== null || !state.ready_to_execute}
              title={
                state.ready_to_execute
                  ? "Permanently delete this workspace"
                  : "Cool-off period has not elapsed yet"
              }
              className="inline-flex items-center justify-center gap-2 rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Skull weight="duotone" className="h-4 w-4" />
              Execute teardown now
            </button>
          </div>
        )}
      </section>

      {!state?.scheduled && !loading && (
        <section className="mt-8 rounded-lg border border-red-300 bg-red-50/40 p-6 shadow-sm dark:border-red-900/60 dark:bg-red-950/20">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-red-900 dark:text-red-200">
            <ShieldWarning weight="duotone" className="h-5 w-5" />
            Schedule a teardown
          </div>
          <p className="mb-4 text-sm text-red-900/80 dark:text-red-200/80">
            After the cool-off period elapses, execute will permanently delete
            every classification, audit row, saved view, membership, API key,
            webhook, session, and tenant setting for this workspace. Other
            workspaces are not touched.
          </p>
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
                Confirm workspace id
              </label>
              <input
                type="text"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder={tenant || "workspace id"}
                className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-sm shadow-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500 dark:border-zinc-700 dark:bg-zinc-950"
              />
              {tenant && (
                <p className="mt-1 text-xs text-zinc-500">
                  Must equal{" "}
                  <span className="font-mono">{tenant}</span> exactly.
                </p>
              )}
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
                  Cooling off (hours)
                </label>
                <input
                  type="number"
                  min={1}
                  max={720}
                  value={cooloff}
                  onChange={(e) =>
                    setCooloff(Math.max(1, Math.min(720, +e.target.value || 1)))
                  }
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500 dark:border-zinc-700 dark:bg-zinc-950"
                />
                <p className="mt-1 text-xs text-zinc-500">
                  1 to 720 hours. Default 168 (7 days).
                </p>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
                  Reason (optional)
                </label>
                <input
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value.slice(0, 256))}
                  placeholder="contract ended, account closure"
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500 dark:border-zinc-700 dark:bg-zinc-950"
                />
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs text-zinc-600 dark:text-zinc-400">
              <Timer weight="duotone" className="h-4 w-4" />
              An MFA code is required to schedule, cancel, or execute.
            </div>
            <button
              type="button"
              onClick={doSchedule}
              disabled={busy !== null || !confirm}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Warning weight="duotone" className="h-4 w-4" />
              {busy === "schedule" ? "Scheduling..." : "Schedule teardown"}
            </button>
          </div>
        </section>
      )}

      {result && (
        <section className="mt-8 rounded-lg border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
          <h2 className="mb-3 text-sm font-medium">Teardown receipt</h2>
          <p className="mb-3 text-xs text-zinc-500">
            Workspace <span className="font-mono">{result.tenant_id}</span> was
            permanently deleted. Rows removed:
          </p>
          <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
            {Object.entries(result.deleted)
              .filter(([, n]) => n > 0)
              .sort((a, b) => b[1] - a[1])
              .map(([table, n]) => (
                <li
                  key={table}
                  className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800"
                >
                  <span className="font-mono">{table}</span>
                  <span className="tabular-nums">{n}</span>
                </li>
              ))}
          </ul>
        </section>
      )}
    </div>
  );
}
