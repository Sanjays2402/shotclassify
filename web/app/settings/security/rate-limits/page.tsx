"use client";

// Per-workspace API rate-limit configuration.
//
// This page reads and writes the workspace rate-limit policy that gates
// every /v1/* programmatic request. The backing API requires an
// admin-scoped sk_live key. We do not embed the key in the page bundle;
// the admin pastes it once per session, it is held in component state,
// and only sent to /api/ratelimit on the same origin.
//
// Edits are atomic. Lowering a limit takes effect on the very next
// request because counters are checked live, not cached.

import { useEffect, useMemo, useState } from "react";
import {
  Gauge,
  ShieldCheck,
  Buildings,
  Key as KeyIcon,
  ArrowsClockwise,
  WarningCircle,
  CheckCircle,
} from "@phosphor-icons/react/dist/ssr";

type Limits = {
  workspace_per_minute: number;
  workspace_per_day: number;
  key_per_minute: number;
  key_per_day: number;
};

type ConfigResponse = {
  workspace_id: string;
  plan: "free" | "pro" | "team" | "custom";
  limits: Limits;
  used: {
    workspace_per_minute_used: number;
    workspace_per_day_used: number;
    key_per_minute_used: number;
    key_per_day_used: number;
  };
  plan_defaults: Record<"free" | "pro" | "team", Limits>;
};

const PLANS = ["free", "pro", "team", "custom"] as const;

function fmt(n: number): string {
  return n.toLocaleString("en-US");
}

function pct(used: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

function Meter({ used, limit, label }: { used: number; limit: number; label: string }) {
  const p = pct(used, limit);
  const tone = p >= 90 ? "bg-red-500" : p >= 70 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-zinc-700 dark:text-zinc-300">{label}</span>
        <span className="font-mono text-xs text-zinc-500">
          {fmt(used)} / {fmt(limit)}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
        <div className={`h-full ${tone} transition-all`} style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3" aria-hidden>
      <div className="h-4 w-32 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="h-2 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="h-4 w-40 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="h-2 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
    </div>
  );
}

export default function RateLimitsPage() {
  const [token, setToken] = useState("");
  const [data, setData] = useState<ConfigResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [draft, setDraft] = useState<Limits | null>(null);
  const [draftPlan, setDraftPlan] = useState<ConfigResponse["plan"]>("free");

  const load = async (tok: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/ratelimit", {
        headers: { authorization: `Bearer ${tok}` },
        cache: "no-store",
      });
      if (res.status === 401 || res.status === 403) {
        setError("That key is not authorized. Use an admin-scoped API key.");
        setData(null);
        return;
      }
      if (!res.ok) {
        setError(`Request failed: HTTP ${res.status}`);
        return;
      }
      const json = (await res.json()) as ConfigResponse;
      setData(json);
      setDraft({ ...json.limits });
      setDraftPlan(json.plan);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Auto-refresh usage every 10s without nuking the editing state.
    if (!token || !data) return;
    const t = window.setInterval(async () => {
      try {
        const res = await fetch("/api/ratelimit", {
          headers: { authorization: `Bearer ${token}` },
          cache: "no-store",
        });
        if (res.ok) {
          const json = (await res.json()) as ConfigResponse;
          setData((prev) => (prev ? { ...json, limits: prev.limits } : json));
        }
      } catch {
        // transient errors are fine; we just skip this tick
      }
    }, 10_000);
    return () => window.clearInterval(t);
  }, [token, data]);

  const save = async () => {
    if (!token || !draft) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/ratelimit", {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ plan: draftPlan, limits: draft }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j?.error?.message ?? `Save failed: HTTP ${res.status}`);
        return;
      }
      const j = await res.json();
      setData((prev) => (prev ? { ...prev, plan: j.config.plan, limits: j.config.limits } : prev));
      setDraft({ ...j.config.limits });
      setDraftPlan(j.config.plan);
      setSavedAt(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setLoading(false);
    }
  };

  const applyPlanDefaults = (plan: ConfigResponse["plan"]) => {
    setDraftPlan(plan);
    if (plan !== "custom" && data) {
      setDraft({ ...data.plan_defaults[plan] });
    }
  };

  const dirty = useMemo(() => {
    if (!data || !draft) return false;
    if (draftPlan !== data.plan) return true;
    const a = data.limits;
    return (
      a.workspace_per_minute !== draft.workspace_per_minute ||
      a.workspace_per_day !== draft.workspace_per_day ||
      a.key_per_minute !== draft.key_per_minute ||
      a.key_per_day !== draft.key_per_day
    );
  }, [data, draft, draftPlan]);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="mb-6 flex items-start gap-3">
        <Gauge size={28} weight="duotone" className="mt-1 text-zinc-700 dark:text-zinc-300" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">API rate limits</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Per workspace and per key quotas for every /v1 endpoint. Exceeded
            requests get HTTP 429 with a Retry-After header. Changes apply on
            the very next request.
          </p>
        </div>
      </header>

      <section className="mb-6 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <label className="block text-sm font-medium">Admin API key</label>
        <p className="mt-1 text-xs text-zinc-500">
          Paste an sk_live key with the admin scope. We send it on this origin
          only; it is not stored.
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="sk_live_..."
            autoComplete="off"
            className="flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="button"
            onClick={() => token && load(token)}
            disabled={!token || loading}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-100"
          >
            <ShieldCheck size={16} weight="duotone" /> Load
          </button>
        </div>
        {error && (
          <p className="mt-3 flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
            <WarningCircle size={16} weight="duotone" /> {error}
          </p>
        )}
      </section>

      {loading && !data && <Skeleton />}

      {!loading && !data && !error && (
        <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
          Load a config to see live usage and edit limits.
        </div>
      )}

      {data && draft && (
        <>
          <section className="mb-6 rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Buildings size={18} weight="duotone" /> Workspace
                <span className="font-mono text-xs text-zinc-500">{data.workspace_id}</span>
              </div>
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium uppercase tracking-wide text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                {data.plan}
              </span>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Meter label="Workspace per minute" used={data.used.workspace_per_minute_used} limit={data.limits.workspace_per_minute} />
              <Meter label="Workspace per day" used={data.used.workspace_per_day_used} limit={data.limits.workspace_per_day} />
              <Meter label="Calling key per minute" used={data.used.key_per_minute_used} limit={data.limits.key_per_minute} />
              <Meter label="Calling key per day" used={data.used.key_per_day_used} limit={data.limits.key_per_day} />
            </div>
          </section>

          <section className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="mb-1 flex items-center gap-2 text-sm font-medium">
              <KeyIcon size={18} weight="duotone" /> Edit limits
            </h2>
            <p className="mb-4 text-xs text-zinc-500">
              Pick a plan preset or switch to custom and tune each value.
            </p>

            <div className="mb-4 flex flex-wrap gap-2">
              {PLANS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => applyPlanDefaults(p)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium capitalize ${
                    draftPlan === p
                      ? "border-zinc-900 bg-zinc-900 text-white dark:border-white dark:bg-white dark:text-zinc-900"
                      : "border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["workspace_per_minute", "Workspace per minute"],
                  ["workspace_per_day", "Workspace per day"],
                  ["key_per_minute", "Per key per minute"],
                  ["key_per_day", "Per key per day"],
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="block">
                  <span className="block text-xs font-medium text-zinc-600 dark:text-zinc-400">{label}</span>
                  <input
                    type="number"
                    min={0}
                    step={1}
                    inputMode="numeric"
                    value={draft[k]}
                    onChange={(e) =>
                      setDraft({ ...draft, [k]: Math.max(0, Math.floor(Number(e.target.value) || 0)) })
                    }
                    className="mt-1 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
                  />
                </label>
              ))}
            </div>

            <div className="mt-5 flex items-center justify-between gap-3">
              <p className="text-xs text-zinc-500">
                {savedAt && Date.now() - savedAt < 5000 ? (
                  <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                    <CheckCircle size={14} weight="duotone" /> Saved
                  </span>
                ) : dirty ? (
                  "Unsaved changes"
                ) : (
                  "All changes saved"
                )}
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (data) {
                      setDraft({ ...data.limits });
                      setDraftPlan(data.plan);
                    }
                  }}
                  disabled={!dirty || loading}
                  className="inline-flex items-center gap-2 rounded-md border border-zinc-300 px-3 py-2 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
                >
                  <ArrowsClockwise size={16} weight="duotone" /> Revert
                </button>
                <button
                  type="button"
                  onClick={save}
                  disabled={!dirty || loading}
                  className="inline-flex items-center gap-2 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-100"
                >
                  Save
                </button>
              </div>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
