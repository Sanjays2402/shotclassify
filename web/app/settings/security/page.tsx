"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  Shield,
  Plus,
  Trash,
  FloppyDisk,
  Warning,
  Lock,
  Globe,
  CheckCircle,
  Clock,
  Broom,
  Devices,
  SignOut,
  Key as KeyIcon,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type AllowlistResponse = {
  tenant_id: string;
  cidrs: string[];
};

type ApiError = Error & { status?: number };

function isProbablyCidr(s: string): boolean {
  const v = s.trim();
  if (!v) return false;
  // IPv4 with optional /N, IPv6 with optional /N. Loose check; the API
  // is authoritative and returns 422 on a bad entry.
  return /^[0-9a-fA-F:.]+(\/\d{1,3})?$/.test(v);
}

export default function SecuritySettingsPage() {
  const { data, error, isLoading, mutate } = useSWR<AllowlistResponse>(
    "/api/settings/security/ip-allowlist",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [draft, setDraft] = useState<string[]>([]);
  const [newEntry, setNewEntry] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  // Initialize the draft once the loaded value arrives so editing is local
  // until the operator commits with Save.
  useEffect(() => {
    if (data?.cidrs) setDraft(data.cidrs);
  }, [data?.cidrs]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const dirty = useMemo(() => {
    if (!data) return false;
    const a = [...data.cidrs].sort();
    const b = [...draft].sort();
    if (a.length !== b.length) return true;
    return a.some((v, i) => v !== b[i]);
  }, [data, draft]);

  const addEntry = () => {
    const v = newEntry.trim();
    if (!v) return;
    if (!isProbablyCidr(v)) {
      setFlash({ kind: "err", msg: `Not a CIDR or IP: ${v}` });
      return;
    }
    if (draft.includes(v)) {
      setFlash({ kind: "err", msg: `${v} already in the list.` });
      return;
    }
    setDraft([...draft, v]);
    setNewEntry("");
    setFlash(null);
  };

  const removeEntry = (idx: number) => {
    setDraft(draft.filter((_, i) => i !== idx));
  };

  const save = async () => {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/ip-allowlist", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cidrs: draft }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `${res.status} ${res.statusText}`);
      }
      const body = (await res.json()) as AllowlistResponse;
      setDraft(body.cidrs);
      setFlash({
        kind: "ok",
        msg: body.cidrs.length
          ? `Saved. ${body.cidrs.length} range${body.cidrs.length === 1 ? "" : "s"} active.`
          : "Saved. Allowlist disabled; every source IP is permitted.",
      });
      mutate();
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Save failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <header className="flex items-center gap-3">
        <Shield size={28} weight="duotone" className="text-emerald-600" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Security settings
          </h1>
          <p className="text-sm text-zinc-500">
            Workspace controls for network access. Changes apply immediately
            and are written to the audit log.
          </p>
        </div>
      </header>

      <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center gap-2 mb-2">
          <Globe size={20} weight="duotone" className="text-sky-600" />
          <h2 className="text-base font-semibold">IP allowlist</h2>
          {data?.tenant_id ? (
            <span className="ml-auto rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
              tenant: {data.tenant_id}
            </span>
          ) : null}
        </div>
        <p className="text-sm text-zinc-500 mb-4">
          Restrict API and dashboard access to a list of CIDR ranges (for
          example <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-900">10.0.0.0/24</code>
          {" "}or a single IP like <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-900">203.0.113.42</code>).
          Leave the list empty to allow every source IP.
        </p>

        {isLoading ? (
          <div className="space-y-2" aria-busy="true">
            <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
            <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
            <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
          </div>
        ) : unauth ? (
          <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <Lock size={18} weight="duotone" />
            <div>Sign in to manage workspace security settings.</div>
          </div>
        ) : forbidden ? (
          <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <Warning size={18} weight="duotone" />
            <div>Only workspace admins can view or change the IP allowlist.</div>
          </div>
        ) : status ? (
          <div className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">
            <Warning size={18} weight="duotone" />
            <div>{status.message}</div>
          </div>
        ) : (
          <>
            {draft.length === 0 ? (
              <div className="rounded-md border border-dashed border-zinc-300 bg-zinc-50 p-4 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
                No ranges configured. The allowlist is currently disabled and
                every source IP can reach the API.
              </div>
            ) : (
              <ul className="divide-y divide-zinc-200 rounded-md border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
                {draft.map((cidr, idx) => (
                  <li
                    key={`${cidr}-${idx}`}
                    className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                  >
                    <code className="font-mono text-zinc-800 dark:text-zinc-200">
                      {cidr}
                    </code>
                    <button
                      type="button"
                      onClick={() => removeEntry(idx)}
                      className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-50 hover:text-rose-700 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900"
                      aria-label={`Remove ${cidr}`}
                    >
                      <Trash size={14} weight="duotone" /> Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <form
              className="mt-4 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                addEntry();
              }}
            >
              <input
                type="text"
                inputMode="text"
                value={newEntry}
                onChange={(e) => setNewEntry(e.target.value)}
                placeholder="10.0.0.0/24 or 203.0.113.42"
                aria-label="CIDR or IP to add"
                className="min-w-0 flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-950"
              />
              <button
                type="submit"
                className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-950 dark:hover:bg-zinc-900"
              >
                <Plus size={16} weight="duotone" /> Add
              </button>
            </form>

            <div className="mt-4 flex items-center gap-3">
              <button
                type="button"
                onClick={save}
                disabled={!dirty || busy}
                className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? (
                  <>
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    Saving
                  </>
                ) : (
                  <>
                    <FloppyDisk size={16} weight="duotone" /> Save changes
                  </>
                )}
              </button>
              {dirty ? (
                <span className="text-xs text-amber-700 dark:text-amber-300">
                  Unsaved changes
                </span>
              ) : null}
              {flash ? (
                <span
                  role="status"
                  className={
                    "ml-auto inline-flex items-center gap-1 text-xs " +
                    (flash.kind === "ok"
                      ? "text-emerald-700 dark:text-emerald-300"
                      : "text-rose-700 dark:text-rose-300")
                  }
                >
                  {flash.kind === "ok" ? (
                    <CheckCircle size={14} weight="duotone" />
                  ) : (
                    <Warning size={14} weight="duotone" />
                  )}
                  {flash.msg}
                </span>
              ) : null}
            </div>
          </>
        )}
      </section>

      <section className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
        <p>
          The API and the dashboard both honor the allowlist. Healthcheck and
          metrics endpoints stay reachable so probes never trip when the list
          is wrong. If you lock yourself out, an operator with shell access
          can clear the list with{" "}
          <code className="rounded bg-white px-1 py-0.5 text-xs dark:bg-zinc-950">
            curl -X PUT
          </code>{" "}
          and a server-side admin API key.
        </p>
      </section>

      <RetentionSection />
      <SsoSection />
      <TenantOidcSection />
      <SessionPolicySection />
      <ApiKeyTtlPolicySection />
      <MfaPolicySection />
      <CorsOriginsSection />
      <SessionsSection />
    </div>
  );
}

type SessionRow = {
  id: string;
  principal: string;
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

function formatWhen(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function shortAgent(ua: string | null): string {
  if (!ua) return "Unknown client";
  // Trim to something recognizable; full UA is in the tooltip.
  const m =
    ua.match(/(Edg|Chrome|Firefox|Safari|curl|httpx|python-requests)[\/ ]?[\d.]*/i) ??
    null;
  return m ? m[0] : ua.slice(0, 48);
}

function SessionsSection() {
  const { data, error, isLoading, mutate } = useSWR<SessionsResponse>(
    "/api/sessions",
    fetcher,
    { revalidateOnFocus: false },
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const revokeOne = async (id: string) => {
    setBusy(id);
    setFlash(null);
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Revoke failed (${res.status}).`);
      setFlash({ kind: "ok", msg: "Session revoked." });
      await mutate();
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Revoke failed.",
      });
    } finally {
      setBusy(null);
    }
  };

  const revokeAllOthers = async () => {
    if (
      !confirm(
        "Sign out of every other session? Other devices will need to log in again.",
      )
    )
      return;
    setBusy("__all__");
    setFlash(null);
    try {
      const res = await fetch("/api/sessions/revoke-all?keep_current=true", {
        method: "POST",
      });
      if (!res.ok) throw new Error(`Revoke-all failed (${res.status}).`);
      const body = (await res.json()) as { revoked: number };
      setFlash({
        kind: "ok",
        msg: `Signed ${body.revoked} other ${body.revoked === 1 ? "session" : "sessions"} out.`,
      });
      await mutate();
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Revoke-all failed.",
      });
    } finally {
      setBusy(null);
    }
  };

  const sessions = data?.sessions ?? [];
  const otherCount = sessions.filter((s) => !s.current && !s.revoked_at).length;

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-2">
        <Devices size={20} weight="duotone" className="text-indigo-600" />
        <h2 className="text-base font-semibold">Active sessions</h2>
        <button
          type="button"
          onClick={revokeAllOthers}
          disabled={busy !== null || otherCount === 0}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200 dark:hover:bg-zinc-900"
        >
          <SignOut size={14} weight="duotone" />
          Sign out other sessions
        </button>
      </div>
      <p className="text-sm text-zinc-500 mb-4">
        Every signed-in device for this account. Revoke a session to log that
        device out immediately even if the cookie is still on disk.
      </p>

      {flash ? (
        <div
          className={`mb-3 rounded-md px-3 py-2 text-sm ${
            flash.kind === "ok"
              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
              : "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
          }`}
        >
          {flash.msg}
        </div>
      ) : null}

      {isLoading ? (
        <div className="space-y-2" aria-busy="true">
          <div className="h-14 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
          <div className="h-14 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
        </div>
      ) : unauth ? (
        <p className="text-sm text-zinc-500">Sign in to view your sessions.</p>
      ) : forbidden ? (
        <p className="text-sm text-zinc-500">
          This account is not permitted to view sessions.
        </p>
      ) : status ? (
        <p className="text-sm text-rose-600">
          {status.message || "Could not load sessions."}
        </p>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No active sessions. API-key callers do not create sessions.
        </p>
      ) : (
        <ul className="divide-y divide-zinc-100 rounded-md border border-zinc-200 dark:divide-zinc-900 dark:border-zinc-800">
          {sessions.map((s) => (
            <li
              key={s.id}
              className="flex flex-col gap-2 px-3 py-3 text-sm sm:flex-row sm:items-center sm:gap-4"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className="truncate font-medium text-zinc-900 dark:text-zinc-100"
                    title={s.user_agent ?? ""}
                  >
                    {shortAgent(s.user_agent)}
                  </span>
                  {s.current ? (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                      This device
                    </span>
                  ) : null}
                  {s.revoked_at ? (
                    <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
                      Revoked
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-zinc-500">
                  <span>IP {s.client_ip ?? "unknown"}</span>
                  <span>Last seen {formatWhen(s.last_seen_at)}</span>
                  <span>Expires {formatWhen(s.expires_at)}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => revokeOne(s.id)}
                disabled={busy !== null || !!s.revoked_at}
                aria-label={s.current ? "Sign out of this device" : "Revoke session"}
                className="inline-flex items-center gap-1.5 self-start rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 sm:self-auto dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200 dark:hover:bg-zinc-900"
              >
                <Trash size={14} weight="duotone" />
                {s.current ? "Sign out" : "Revoke"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type RetentionResponse = {
  tenant_id: string;
  retention_days: number | null;
  enabled: boolean;
};

function RetentionSection() {
  const { data, error, isLoading, mutate } = useSWR<RetentionResponse>(
    "/api/settings/security/retention",
    fetcher,
    { revalidateOnFocus: false },
  );
  const [draft, setDraft] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [purging, setPurging] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    if (data) setDraft(data.retention_days ? String(data.retention_days) : "");
  }, [data?.retention_days]);

  const current = data?.retention_days ?? null;
  const parsed = draft.trim() === "" ? 0 : Number(draft);
  const validNum = Number.isInteger(parsed) && parsed >= 0 && parsed <= 3650;
  const dirty =
    validNum && (parsed || 0) !== (current ?? 0);
  const unauth = error && (error as ApiError).status === 401;
  const forbidden = error && (error as ApiError).status === 403;

  async function save() {
    if (!dirty) return;
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/settings/security/retention", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          retention_days: parsed === 0 ? null : parsed,
        }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || r.statusText);
      setFlash({
        kind: "ok",
        msg: body.enabled
          ? `Saved. Data older than ${body.retention_days} days will be purged.`
          : "Saved. Retention disabled, data kept indefinitely.",
      });
      mutate();
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Save failed.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    setPurging(true);
    setFlash(null);
    try {
      const r = await fetch("/api/settings/security/retention/run", {
        method: "POST",
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || r.statusText);
      setFlash({
        kind: "ok",
        msg: `Purge complete. Removed ${body.removed} classifications older than ${body.retention_days} days.`,
      });
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Purge failed.",
      });
    } finally {
      setPurging(false);
    }
  }

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-2">
        <Clock size={20} weight="duotone" className="text-emerald-600" />
        <h2 className="text-base font-semibold">Data retention policy</h2>
      </div>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
        Auto-purge classifications older than this many days. Audit log
        entries are kept for compliance. Leave empty or set to 0 to keep
        everything indefinitely.
      </p>

      {isLoading ? (
        <div
          className="mt-4 h-9 w-48 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900"
          aria-label="Loading retention policy"
        />
      ) : unauth ? (
        <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">
          Sign in to view the retention policy.
        </p>
      ) : forbidden ? (
        <p className="mt-4 text-sm text-rose-700 dark:text-rose-300">
          Admin role required.
        </p>
      ) : error ? (
        <p className="mt-4 text-sm text-rose-700 dark:text-rose-300">
          Could not load: {String((error as Error).message)}
        </p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
              Retention window (days)
              <input
                type="number"
                min={0}
                max={3650}
                step={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="0 = disabled"
                className="w-40 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-950"
              />
            </label>
            <button
              type="button"
              onClick={save}
              disabled={!dirty || !validNum || busy}
              className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? (
                <>
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Saving
                </>
              ) : (
                <>
                  <FloppyDisk size={16} weight="duotone" /> Save policy
                </>
              )}
            </button>
            <button
              type="button"
              onClick={runNow}
              disabled={!current || purging}
              className="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm font-medium hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:hover:bg-zinc-900"
              title={current ? "Run a purge immediately" : "Set a policy first"}
            >
              {purging ? (
                <>
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-zinc-500 border-t-transparent" />
                  Purging
                </>
              ) : (
                <>
                  <Broom size={16} weight="duotone" /> Run purge now
                </>
              )}
            </button>
          </div>

          {!validNum && draft !== "" && (
            <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
              Enter a whole number between 0 and 3650.
            </p>
          )}

          <div className="mt-3 text-xs text-zinc-500 dark:text-zinc-500">
            Status:{" "}
            {current ? (
              <span className="font-medium text-emerald-700 dark:text-emerald-300">
                Active, {current} days
              </span>
            ) : (
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                Disabled, keep forever
              </span>
            )}
            {data?.tenant_id ? (
              <>
                {" "}
                ·{" "}
                <span className="font-mono">tenant {data.tenant_id}</span>
              </>
            ) : null}
          </div>

          {flash ? (
            <p
              role="status"
              className={
                "mt-3 inline-flex items-center gap-1 text-xs " +
                (flash.kind === "ok"
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-rose-700 dark:text-rose-300")
              }
            >
              {flash.kind === "ok" ? (
                <CheckCircle size={14} weight="duotone" />
              ) : (
                <Warning size={14} weight="duotone" />
              )}
              {flash.msg}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

type SsoConfig = {
  tenant_id: string;
  enforced: boolean;
  domain: string | null;
  provider: string | null;
  auto_join_role: "viewer" | "operator" | null;
};

type SsoPublic = { enabled: boolean; issuer: string | null };

function SsoSection() {
  const { data, error, isLoading, mutate } = useSWR<SsoConfig>(
    "/api/settings/security/sso",
    fetcher,
    { revalidateOnFocus: false },
  );
  const { data: pub } = useSWR<SsoPublic>(
    `/api/sso-config`,
    fetcher,
    { revalidateOnFocus: false },
  );
  const [enforced, setEnforced] = useState(false);
  const [domain, setDomain] = useState("");
  const [provider, setProvider] = useState("");
  const [autoJoin, setAutoJoin] = useState<"" | "viewer" | "operator">("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  useEffect(() => {
    if (data) {
      setEnforced(data.enforced);
      setDomain(data.domain ?? "");
      setProvider(data.provider ?? "");
      setAutoJoin((data.auto_join_role ?? "") as "" | "viewer" | "operator");
    }
  }, [data]);

  const status = error as (Error & { status?: number }) | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const dirty =
    !!data &&
    (enforced !== data.enforced ||
      (domain || null) !== data.domain ||
      (provider || null) !== data.provider ||
      (autoJoin || null) !== data.auto_join_role);

  const save = async () => {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/sso", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          enforced,
          domain: domain.trim() || null,
          provider: provider.trim() || null,
          auto_join_role: autoJoin || null,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `${res.status} ${res.statusText}`);
      }
      const body = (await res.json()) as SsoConfig;
      setFlash({
        kind: "ok",
        msg: body.enforced
          ? "Saved. SSO is required for this workspace. Existing non-SSO sessions are now rejected."
          : "Saved. SSO is configured but not enforced.",
      });
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: e instanceof Error ? e.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <header className="mb-4 flex items-start gap-3">
        <KeyIcon size={22} weight="duotone" className="mt-0.5 text-emerald-600" />
        <div className="flex-1">
          <h2 className="text-lg font-semibold tracking-tight">Single sign-on (OIDC)</h2>
          <p className="text-sm text-zinc-500">
            Route users in your email domain through your identity provider
            (Google Workspace, Okta, Azure AD). Turn on enforcement to reject
            any session that did not flow through SSO.
          </p>
        </div>
        {pub ? (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              pub.enabled
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400"
            }`}
            title={pub.issuer ?? ""}
          >
            {pub.enabled ? "IdP configured" : "IdP not configured"}
          </span>
        ) : null}
      </header>

      {isLoading ? (
        <div className="h-24 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
      ) : unauth ? (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <Lock size={16} weight="duotone" />
          Sign in to manage SSO settings.
        </div>
      ) : forbidden ? (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <Lock size={16} weight="duotone" />
          Only workspace admins can configure SSO.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Email domain</span>
              <input
                type="text"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="acme.com"
                spellCheck={false}
                className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900"
              />
              <span className="text-xs text-zinc-500">
                Users signing in with this domain are routed to this workspace.
              </span>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Provider label</span>
              <input
                type="text"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                placeholder="Okta"
                spellCheck={false}
                className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900"
              />
              <span className="text-xs text-zinc-500">
                Shown on the sign-in page. Free-form (Google, Okta, Azure AD).
              </span>
            </label>
          </div>

          <label className="mt-4 flex flex-col gap-1 rounded-md border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <span className="font-medium">Domain auto-join</span>
            <span className="text-xs text-zinc-500">
              When a user from this domain signs in via SSO for the first
              time, automatically add them to the workspace with this role.
              Leave off to keep invite-only onboarding. The admin role is
              never available here to prevent privilege escalation through
              DNS control.
            </span>
            <select
              value={autoJoin}
              onChange={(e) => setAutoJoin(e.target.value as "" | "viewer" | "operator")}
              disabled={!domain.trim()}
              className="mt-1 max-w-xs rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 disabled:cursor-not-allowed disabled:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:disabled:bg-zinc-950"
            >
              <option value="">Off (invite only)</option>
              <option value="viewer">Viewer</option>
              <option value="operator">Operator</option>
            </select>
            {!domain.trim() && autoJoin ? (
              <span className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                Set an email domain above to enable auto-join.
              </span>
            ) : null}
          </label>

          <label className="mt-4 flex items-start gap-3 rounded-md border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <input
              type="checkbox"
              checked={enforced}
              onChange={(e) => setEnforced(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
            />
            <span className="flex-1">
              <span className="font-medium">Require SSO for this workspace</span>
              <span className="block text-xs text-zinc-500">
                Reject any session that was not minted via the OIDC callback.
                API key callers (machine-to-machine) remain allowed.
              </span>
            </span>
          </label>

          <div className="mt-4 flex items-center justify-between">
            <p className="text-xs text-zinc-500">
              Status: {data?.enforced ? "Enforced" : "Available but not required"}
              {data?.domain ? <> · Domain {data.domain}</> : null}
              {data?.auto_join_role ? <> · Auto-join {data.auto_join_role}</> : null}
            </p>
            <button
              type="button"
              onClick={save}
              disabled={!dirty || busy}
              className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-zinc-300 dark:disabled:bg-zinc-700"
            >
              <FloppyDisk size={16} weight="duotone" />
              {busy ? "Saving" : "Save"}
            </button>
          </div>
          {flash ? (
            <p
              className={`mt-3 inline-flex items-center gap-1 text-sm ${
                flash.kind === "ok"
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-red-700 dark:text-red-400"
              }`}
            >
              {flash.kind === "ok" ? (
                <CheckCircle size={14} weight="duotone" />
              ) : (
                <Warning size={14} weight="duotone" />
              )}
              {flash.msg}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
type SessionPolicyResponse = {
  tenant_id: string;
  session_ttl_minutes: number | null;
  session_idle_minutes?: number | null;
  default_minutes: number;
  effective_minutes: number;
  min_minutes: number;
  max_minutes: number;
  idle_min_minutes?: number;
  idle_max_minutes?: number;
  clipped?: number;
};

function SessionPolicySection() {
  const { data, error, isLoading, mutate } = useSWR<SessionPolicyResponse>(
    "/api/settings/security/sessions",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [override, setOverride] = useState<boolean>(false);
  const [value, setValue] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    if (!data) return;
    if (data.session_ttl_minutes != null) {
      setOverride(true);
      setValue(String(data.session_ttl_minutes));
    } else {
      setOverride(false);
      setValue(String(data.default_minutes));
    }
  }, [data?.session_ttl_minutes, data?.default_minutes]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const dirty = useMemo(() => {
    if (!data) return false;
    if (!override) return data.session_ttl_minutes !== null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return false;
    return Math.trunc(parsed) !== data.session_ttl_minutes;
  }, [data, override, value]);

  const presets: Array<{ label: string; minutes: number }> = [
    { label: "1 hour", minutes: 60 },
    { label: "8 hours", minutes: 480 },
    { label: "1 day", minutes: 1440 },
    { label: "7 days", minutes: 10080 },
    { label: "30 days", minutes: 43200 },
  ];

  async function save() {
    if (!data) return;
    setBusy(true);
    setFlash(null);
    try {
      let body: { session_ttl_minutes: number | null };
      if (!override) {
        body = { session_ttl_minutes: null };
      } else {
        const parsed = Math.trunc(Number(value));
        if (!Number.isFinite(parsed)) {
          setFlash({ kind: "err", msg: "Enter a whole number of minutes." });
          setBusy(false);
          return;
        }
        if (parsed < data.min_minutes || parsed > data.max_minutes) {
          setFlash({
            kind: "err",
            msg: `Minutes must be between ${data.min_minutes} and ${data.max_minutes}.`,
          });
          setBusy(false);
          return;
        }
        body = { session_ttl_minutes: parsed };
      }
      const res = await fetch("/api/settings/security/sessions", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        setFlash({ kind: "err", msg: text || `Save failed (${res.status})` });
        setBusy(false);
        return;
      }
      const next: SessionPolicyResponse = await res.json();
      const clipped = next.clipped ?? 0;
      setFlash({
        kind: "ok",
        msg:
          clipped > 0
            ? `Saved. Shortened ${clipped} active session${clipped === 1 ? "" : "s"}.`
            : "Saved.",
      });
      await mutate(next, { revalidate: false });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Save failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-2">
        <Clock size={20} weight="duotone" className="text-violet-600" />
        <h2 className="text-base font-semibold">Session lifetime</h2>
        {data?.tenant_id ? (
          <span className="ml-auto rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
            tenant: {data.tenant_id}
          </span>
        ) : null}
      </div>
      <p className="text-sm text-zinc-500 mb-4">
        How long a signed-in browser session stays valid before the user
        must re-authenticate. Lowering this value also clips active
        sessions whose remaining lifetime would exceed the new ceiling,
        so a long-lived cookie cannot outlive a tightened policy.
      </p>

      {isLoading ? (
        <div className="space-y-2" aria-busy="true">
          <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
          <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
        </div>
      ) : unauth ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Sign in to manage session policy.
        </div>
      ) : forbidden ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Admin role required to change session policy.
        </div>
      ) : !data ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          Could not load session policy.
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
            <span className="text-zinc-500">Current:</span>
            <span className="rounded-md bg-zinc-100 px-2 py-1 font-mono text-xs dark:bg-zinc-900">
              {data.effective_minutes} min
            </span>
            <span className="text-zinc-500">
              ({data.session_ttl_minutes == null ? "global default" : "workspace override"})
            </span>
          </div>

          <label className="mb-3 flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={override}
              onChange={(e) => setOverride(e.target.checked)}
              aria-label="Override the global session lifetime for this workspace"
            />
            <span>
              Override the global default ({data.default_minutes} min) for this workspace.
            </span>
          </label>

          <div className="flex flex-wrap items-center gap-2 mb-3">
            <input
              type="number"
              inputMode="numeric"
              min={data.min_minutes}
              max={data.max_minutes}
              step={1}
              disabled={!override}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-label="Session lifetime in minutes"
              className="w-40 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-mono shadow-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 disabled:cursor-not-allowed disabled:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-950 dark:disabled:bg-zinc-900"
            />
            <span className="text-xs text-zinc-500">
              minutes ({data.min_minutes} to {data.max_minutes})
            </span>
          </div>

          <div className="mb-4 flex flex-wrap gap-2">
            {presets.map((p) => (
              <button
                key={p.minutes}
                type="button"
                disabled={!override}
                onClick={() => setValue(String(p.minutes))}
                className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-xs text-zinc-700 shadow-sm hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900"
              >
                {p.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={!dirty || busy}
              className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-violet-700 disabled:cursor-not-allowed disabled:bg-zinc-300 dark:disabled:bg-zinc-700"
            >
              <FloppyDisk size={16} weight="duotone" />
              {busy ? "Saving" : "Save"}
            </button>
            <span className="text-xs text-zinc-500">
              Step-up MFA may be required.
            </span>
          </div>

          {flash ? (
            <p
              className={`mt-3 inline-flex items-center gap-1 text-sm ${
                flash.kind === "ok"
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-red-700 dark:text-red-400"
              }`}
              role="status"
            >
              {flash.kind === "ok" ? (
                <CheckCircle size={14} weight="duotone" />
              ) : (
                <Warning size={14} weight="duotone" />
              )}
              {flash.msg}
            </p>
          ) : null}
          <SessionIdleControls data={data} mutate={mutate} />
        </>
      )}
    </section>
  );
}

function SessionIdleControls({
  data,
  mutate,
}: {
  data: SessionPolicyResponse;
  mutate: (
    next?: SessionPolicyResponse,
    opts?: { revalidate?: boolean },
  ) => Promise<unknown>;
}) {
  const idleMin = data.idle_min_minutes ?? 5;
  const idleMax = data.idle_max_minutes ?? 43200;
  const [idleOn, setIdleOn] = useState<boolean>(data.session_idle_minutes != null);
  const [idleValue, setIdleValue] = useState<string>(
    String(data.session_idle_minutes ?? 30),
  );
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    setIdleOn(data.session_idle_minutes != null);
    setIdleValue(String(data.session_idle_minutes ?? 30));
  }, [data.session_idle_minutes]);

  const presets = [
    { label: "15 min", minutes: 15 },
    { label: "30 min", minutes: 30 },
    { label: "1 hour", minutes: 60 },
    { label: "4 hours", minutes: 240 },
  ];

  const dirty = useMemo(() => {
    if (!idleOn) return data.session_idle_minutes != null;
    const parsed = Math.trunc(Number(idleValue));
    if (!Number.isFinite(parsed)) return false;
    return parsed !== data.session_idle_minutes;
  }, [data.session_idle_minutes, idleOn, idleValue]);

  async function saveIdle() {
    setBusy(true);
    setFlash(null);
    try {
      let body: { session_idle_minutes: number | null };
      if (!idleOn) {
        body = { session_idle_minutes: null };
      } else {
        const parsed = Math.trunc(Number(idleValue));
        if (!Number.isFinite(parsed)) {
          setFlash({ kind: "err", msg: "Enter a whole number of minutes." });
          setBusy(false);
          return;
        }
        if (parsed < idleMin || parsed > idleMax) {
          setFlash({
            kind: "err",
            msg: `Idle minutes must be between ${idleMin} and ${idleMax}.`,
          });
          setBusy(false);
          return;
        }
        body = { session_idle_minutes: parsed };
      }
      const res = await fetch("/api/settings/security/sessions/idle", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        setFlash({ kind: "err", msg: text || `Save failed (${res.status})` });
        setBusy(false);
        return;
      }
      const next: SessionPolicyResponse = await res.json();
      setFlash({ kind: "ok", msg: "Saved." });
      await mutate(next, { revalidate: false });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Save failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 border-t border-zinc-200 pt-4 dark:border-zinc-800">
      <div className="mb-1 flex items-center gap-2">
        <Clock size={16} weight="duotone" className="text-violet-600" />
        <h3 className="text-sm font-semibold">Idle (inactivity) timeout</h3>
      </div>
      <p className="mb-3 text-sm text-zinc-500">
        Revoke a signed-in browser session if it has been inactive for longer
        than this many minutes. Required by SOC2 CC6.1 and the standard
        enterprise security questionnaire. Leave off to keep the legacy
        behaviour of bounding sessions only by absolute lifetime.
      </p>
      <label className="mb-3 flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={idleOn}
          onChange={(e) => setIdleOn(e.target.checked)}
          aria-label="Enable idle timeout for this workspace"
        />
        <span>Enable idle timeout for this workspace.</span>
      </label>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          type="number"
          inputMode="numeric"
          min={idleMin}
          max={idleMax}
          step={1}
          disabled={!idleOn}
          value={idleValue}
          onChange={(e) => setIdleValue(e.target.value)}
          aria-label="Idle timeout in minutes"
          className="w-40 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-mono shadow-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 disabled:cursor-not-allowed disabled:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-950 dark:disabled:bg-zinc-900"
        />
        <span className="text-xs text-zinc-500">
          minutes ({idleMin} to {idleMax})
        </span>
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {presets.map((p) => (
          <button
            key={p.minutes}
            type="button"
            disabled={!idleOn}
            onClick={() => setIdleValue(String(p.minutes))}
            className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-xs text-zinc-700 shadow-sm hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900"
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={saveIdle}
          disabled={!dirty || busy}
          className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-violet-700 disabled:cursor-not-allowed disabled:bg-zinc-300 dark:disabled:bg-zinc-700"
        >
          <FloppyDisk size={16} weight="duotone" />
          {busy ? "Saving" : "Save idle policy"}
        </button>
        <span className="text-xs text-zinc-500">
          Current:{" "}
          <span className="font-mono">
            {data.session_idle_minutes == null
              ? "off"
              : `${data.session_idle_minutes} min`}
          </span>
        </span>
      </div>
      {flash ? (
        <p
          className={`mt-3 inline-flex items-center gap-1 text-sm ${
            flash.kind === "ok"
              ? "text-emerald-700 dark:text-emerald-400"
              : "text-red-700 dark:text-red-400"
          }`}
          role="status"
        >
          {flash.kind === "ok" ? (
            <CheckCircle size={14} weight="duotone" />
          ) : (
            <Warning size={14} weight="duotone" />
          )}
          {flash.msg}
        </p>
      ) : null}
    </div>
  );
}

type TenantOidcConfig = {
  tenant_id: string;
  configured: boolean;
  issuer: string | null;
  client_id: string | null;
  scopes: string | null;
  client_secret_fingerprint: string | null;
  client_secret_last_four: string | null;
  updated_at: string | null;
};

function TenantOidcSection() {
  const { data, error, isLoading, mutate } = useSWR<TenantOidcConfig>(
    "/api/settings/security/oidc",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [issuer, setIssuer] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [scopes, setScopes] = useState("openid email profile");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  useEffect(() => {
    if (data) {
      setIssuer(data.issuer ?? "");
      setClientId(data.client_id ?? "");
      setScopes(data.scopes ?? "openid email profile");
      setClientSecret("");
    }
  }, [data]);

  const status = error as (Error & { status?: number }) | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const save = async () => {
    setBusy(true);
    setFlash(null);
    try {
      const body: Record<string, string | null> = {
        issuer: issuer.trim() || null,
        client_id: clientId.trim() || null,
        scopes: scopes.trim() || null,
      };
      if (clientSecret) body.client_secret = clientSecret;
      const res = await fetch("/api/settings/security/oidc", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `${res.status} ${res.statusText}`);
      }
      const next = (await res.json()) as TenantOidcConfig;
      setFlash({
        kind: "ok",
        msg: next.configured
          ? "Saved. Sign-ins for your SSO domain will now use your own identity provider."
          : "Saved. Per-tenant OIDC is cleared; sign-ins fall back to the deployment IdP.",
      });
      setClientSecret("");
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: e instanceof Error ? e.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (!confirm("Clear this workspace's OIDC identity provider? Sign-ins will fall back to the deployment IdP.")) return;
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/oidc", { method: "DELETE" });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `${res.status} ${res.statusText}`);
      }
      setIssuer("");
      setClientId("");
      setScopes("openid email profile");
      setClientSecret("");
      setFlash({ kind: "ok", msg: "Cleared." });
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: e instanceof Error ? e.message : "Clear failed." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <header className="mb-4 flex items-start gap-3">
        <KeyIcon size={22} weight="duotone" className="mt-0.5 text-indigo-600" />
        <div className="flex-1">
          <h2 className="text-lg font-semibold tracking-tight">Your own identity provider</h2>
          <p className="text-sm text-zinc-500">
            Register your workspace&apos;s own OIDC application (Okta, Azure AD,
            Google Workspace, Auth0, Keycloak). When a user signs in with an
            email in your SSO domain, we redirect them to your IdP instead of
            ours. Your client secret is stored encrypted at rest and never
            shown to anyone, including operators.
          </p>
        </div>
        {data ? (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              data.configured
                ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400"
            }`}
          >
            {data.configured ? "Configured" : "Not configured"}
          </span>
        ) : null}
      </header>

      {isLoading ? (
        <div className="h-32 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
      ) : unauth ? (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <Lock size={16} weight="duotone" />
          Sign in to manage your identity provider.
        </div>
      ) : forbidden ? (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <Lock size={16} weight="duotone" />
          Only workspace admins can configure the identity provider.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="block text-sm">
              <span className="mb-1 block text-zinc-600 dark:text-zinc-400">Issuer URL</span>
              <input
                type="url"
                value={issuer}
                onChange={(e) => setIssuer(e.target.value)}
                placeholder="https://your-tenant.okta.com"
                className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-zinc-600 dark:text-zinc-400">Client ID</span>
              <input
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="0oab1c2d3e4f5g6h7i"
                className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </label>
            <label className="block text-sm md:col-span-2">
              <span className="mb-1 block text-zinc-600 dark:text-zinc-400">
                Client secret
                {data?.configured ? (
                  <span className="ml-2 text-xs text-zinc-400">
                    Stored. Leave blank to keep existing.
                    {data.client_secret_last_four
                      ? ` Ends in ${data.client_secret_last_four}.`
                      : ""}
                  </span>
                ) : null}
              </span>
              <input
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder={data?.configured ? "(unchanged)" : "Paste the client secret"}
                autoComplete="new-password"
                className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 font-mono text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </label>
            <label className="block text-sm md:col-span-2">
              <span className="mb-1 block text-zinc-600 dark:text-zinc-400">Scopes</span>
              <input
                type="text"
                value={scopes}
                onChange={(e) => setScopes(e.target.value)}
                placeholder="openid email profile"
                className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 font-mono text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </label>
          </div>

          {data?.client_secret_fingerprint ? (
            <p className="mt-3 text-xs text-zinc-500">
              SHA-256 fingerprint of stored secret:{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 dark:bg-zinc-900">
                {data.client_secret_fingerprint.slice(0, 16)}&hellip;
                {data.client_secret_fingerprint.slice(-8)}
              </code>
            </p>
          ) : null}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={busy || (!issuer.trim() && !clientId.trim() && !clientSecret)}
              className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FloppyDisk size={16} weight="duotone" />
              {busy ? "Saving" : "Save"}
            </button>
            {data?.configured ? (
              <button
                type="button"
                onClick={clear}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-sm hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200 dark:hover:bg-zinc-900"
              >
                <Trash size={16} weight="duotone" />
                Clear
              </button>
            ) : null}
            <span className="ml-auto text-xs text-zinc-500">
              Redirect URI to register at your IdP:{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 dark:bg-zinc-900">
                {typeof window !== "undefined"
                  ? `${window.location.origin}/api/auth/sso/callback`
                  : "/api/auth/sso/callback"}
              </code>
            </span>
          </div>

          {flash ? (
            <p
              className={`mt-3 text-sm ${
                flash.kind === "ok"
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-rose-700 dark:text-rose-300"
              }`}
              role="status"
            >
              {flash.msg}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

type ApiKeyTtlResponse = {
  tenant_id: string;
  max_ttl_days: number | null;
  min_days: number;
  max_days: number;
};

function ApiKeyTtlPolicySection() {
  const { data, error, isLoading, mutate } = useSWR<ApiKeyTtlResponse>(
    "/api/settings/security/api-key-ttl",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [enforce, setEnforce] = useState<boolean>(false);
  const [value, setValue] = useState<string>("");
  const [otp, setOtp] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    if (!data) return;
    if (data.max_ttl_days != null) {
      setEnforce(true);
      setValue(String(data.max_ttl_days));
    } else {
      setEnforce(false);
      setValue("90");
    }
  }, [data?.max_ttl_days]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const presets: Array<{ label: string; days: number }> = [
    { label: "30 days", days: 30 },
    { label: "60 days", days: 60 },
    { label: "90 days", days: 90 },
    { label: "180 days", days: 180 },
    { label: "1 year", days: 365 },
  ];

  async function save() {
    if (!data) return;
    setBusy(true);
    setFlash(null);
    try {
      let body: { max_ttl_days: number | null };
      if (!enforce) {
        body = { max_ttl_days: null };
      } else {
        const parsed = Math.trunc(Number(value));
        if (!Number.isFinite(parsed)) {
          setFlash({ kind: "err", msg: "Enter a whole number of days." });
          setBusy(false);
          return;
        }
        if (parsed < data.min_days || parsed > data.max_days) {
          setFlash({
            kind: "err",
            msg: `Days must be between ${data.min_days} and ${data.max_days}.`,
          });
          setBusy(false);
          return;
        }
        body = { max_ttl_days: parsed };
      }
      const headers: Record<string, string> = { "content-type": "application/json" };
      if (otp.trim()) headers["x-mfa-otp"] = otp.trim();
      const res = await fetch("/api/settings/security/api-key-ttl", {
        method: "PUT",
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        setFlash({ kind: "err", msg: text || `Save failed (${res.status})` });
        setBusy(false);
        return;
      }
      const next: ApiKeyTtlResponse = await res.json();
      setFlash({ kind: "ok", msg: "Saved." });
      setOtp("");
      await mutate(next, { revalidate: false });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Save failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-2">
        <KeyIcon size={20} weight="duotone" className="text-amber-600" />
        <h2 className="text-base font-semibold">API key rotation policy</h2>
        {data?.tenant_id ? (
          <span className="ml-auto rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
            tenant: {data.tenant_id}
          </span>
        ) : null}
      </div>
      <p className="text-sm text-zinc-500 mb-4">
        Cap the lifetime of every newly minted or rotated API key in this
        workspace. SOC 2 CC6.1 and most procurement reviews expect a
        documented and enforced rotation window. Existing keys are not
        retroactively shortened, so a tightened policy will not break
        live integrations.
      </p>

      {isLoading ? (
        <div className="space-y-2" aria-busy="true">
          <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
          <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
        </div>
      ) : unauth ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Sign in to manage API key policy.
        </div>
      ) : forbidden ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Admin role required to change API key policy.
        </div>
      ) : !data ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          Could not load API key policy.
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
            <span className="text-zinc-500">Current:</span>
            <span className="rounded-md bg-zinc-100 px-2 py-1 font-mono text-xs dark:bg-zinc-900">
              {data.max_ttl_days == null ? "no cap" : `${data.max_ttl_days} days max`}
            </span>
          </div>

          <label className="mb-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enforce}
              onChange={(e) => setEnforce(e.target.checked)}
              className="h-4 w-4 rounded border-zinc-300 text-amber-600 focus:ring-amber-500"
            />
            <span>Enforce a maximum key lifetime for this workspace</span>
          </label>

          {enforce ? (
            <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block text-sm">
                <span className="mb-1 block text-zinc-600 dark:text-zinc-400">
                  Max key lifetime (days)
                </span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={data.min_days}
                  max={data.max_days}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 font-mono text-sm shadow-sm focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500 dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              <div className="flex flex-wrap items-end gap-1.5">
                {presets.map((p) => (
                  <button
                    key={p.days}
                    type="button"
                    onClick={() => setValue(String(p.days))}
                    className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-700 shadow-sm hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200 dark:hover:bg-zinc-900"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <label className="mb-3 block text-sm">
            <span className="mb-1 block text-zinc-600 dark:text-zinc-400">
              MFA code (required to save)
            </span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              placeholder="6 digit code"
              className="w-40 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 font-mono text-sm shadow-sm focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500 dark:border-zinc-700 dark:bg-zinc-900"
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FloppyDisk size={16} weight="duotone" />
              {busy ? "Saving" : "Save policy"}
            </button>
            <span className="text-xs text-zinc-500">
              Range: {data.min_days} to {data.max_days} days.
            </span>
          </div>

          {flash ? (
            <p
              className={`mt-3 text-sm ${
                flash.kind === "ok"
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-rose-700 dark:text-rose-300"
              }`}
              role="status"
            >
              {flash.msg}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

type MfaPolicyResponse = {
  tenant_id: string;
  required: boolean;
};

function MfaPolicySection() {
  const { data, error, isLoading, mutate } = useSWR<MfaPolicyResponse>(
    "/api/settings/security/mfa-policy",
    fetcher,
    { revalidateOnFocus: false },
  );

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const [required, setRequired] = useState<boolean>(false);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );
  const [mfaToken, setMfaToken] = useState("");

  useEffect(() => {
    if (data) setRequired(Boolean(data.required));
  }, [data?.required]);

  const dirty = useMemo(() => {
    if (!data) return false;
    return Boolean(required) !== Boolean(data.required);
  }, [data, required]);

  async function save() {
    if (!data) return;
    setBusy(true);
    setFlash(null);
    try {
      const headers: Record<string, string> = {
        "content-type": "application/json",
      };
      if (mfaToken.trim()) headers["x-mfa-token"] = mfaToken.trim();
      const res = await fetch("/api/settings/security/mfa-policy", {
        method: "PUT",
        headers,
        body: JSON.stringify({ required }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        let detail = text;
        try {
          const j = JSON.parse(text);
          if (j?.detail) {
            detail =
              typeof j.detail === "string"
                ? j.detail
                : j.detail.detail || JSON.stringify(j.detail);
          }
        } catch {
          /* not JSON */
        }
        if (res.status === 401) {
          setFlash({
            kind: "err",
            msg: "Re-enter your authenticator code in the MFA box and retry.",
          });
        } else {
          setFlash({
            kind: "err",
            msg: detail || `Save failed (${res.status})`,
          });
        }
        setBusy(false);
        return;
      }
      const next: MfaPolicyResponse = await res.json();
      setFlash({
        kind: "ok",
        msg: next.required
          ? "Workspace-wide MFA enrolment is now required."
          : "Workspace-wide MFA requirement cleared.",
      });
      setMfaToken("");
      await mutate(next, { revalidate: false });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Save failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-2">
        <Lock size={20} weight="duotone" className="text-violet-600" />
        <h2 className="text-base font-semibold">Multi-factor authentication</h2>
        {data?.tenant_id ? (
          <span className="ml-auto rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
            tenant: {data.tenant_id}
          </span>
        ) : null}
      </div>
      <p className="text-sm text-zinc-500 mb-4">
        Require every member of this workspace to enrol a TOTP authenticator
        before they can use the API or dashboard. Members without a confirmed
        credential get a 403 on every route except the enrolment surface
        (Settings, sessions, sign out). Machine integrations using scoped API
        keys are not affected.
      </p>

      {isLoading ? (
        <div className="space-y-2" aria-busy="true">
          <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
          <div className="h-9 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
        </div>
      ) : unauth ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Sign in to manage the MFA policy.
        </div>
      ) : forbidden ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Admin role required to change the MFA policy.
        </div>
      ) : !data ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          Could not load the MFA policy.
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-zinc-500">Current:</span>
            <span
              className={
                "rounded-md px-2 py-1 font-mono text-xs " +
                (data.required
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                  : "bg-zinc-100 text-zinc-700 dark:bg-zinc-900 dark:text-zinc-400")
              }
            >
              {data.required ? "REQUIRED" : "OPTIONAL"}
            </span>
          </div>

          <label className="mb-3 flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
              aria-label="Require every member to enrol TOTP MFA"
            />
            <span>
              Require every workspace member to enrol TOTP before they can use
              the API or dashboard.
            </span>
          </label>

          <div className="mb-4 flex flex-col gap-1">
            <label
              htmlFor="mfa-policy-token"
              className="text-xs font-medium text-zinc-600 dark:text-zinc-400"
            >
              Your authenticator code (step-up confirmation)
            </label>
            <input
              id="mfa-policy-token"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={10}
              value={mfaToken}
              onChange={(e) => setMfaToken(e.target.value)}
              placeholder="123456"
              className="w-40 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-mono shadow-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 dark:border-zinc-700 dark:bg-zinc-950"
            />
            <span className="text-xs text-zinc-500">
              Required by the API to confirm this change. Enrol your own TOTP
              under Settings first if you have not already.
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={!dirty || busy}
              className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-violet-700 disabled:cursor-not-allowed disabled:bg-zinc-300 dark:disabled:bg-zinc-700"
            >
              <FloppyDisk size={16} weight="duotone" />
              {busy ? "Saving" : "Save"}
            </button>
            {flash ? (
              <span
                className={
                  "text-xs " +
                  (flash.kind === "ok"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-600 dark:text-red-400")
                }
                role="status"
              >
                {flash.msg}
              </span>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

type CorsOriginsResponse = {
  tenant_id: string;
  origins: string[];
};

function looksLikeOrigin(s: string): boolean {
  const v = s.trim();
  if (!v) return false;
  return /^(https?):\/\/[^\s/?#]+(:\d+)?\/?$/i.test(v);
}

function CorsOriginsSection() {
  const { data, error, isLoading, mutate } = useSWR<CorsOriginsResponse>(
    "/api/settings/security/cors-origins",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [draft, setDraft] = useState<string[]>([]);
  const [newEntry, setNewEntry] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    if (data?.origins) setDraft(data.origins);
  }, [data?.origins]);

  const status = error as ApiError | undefined;
  const forbidden = status?.status === 403;
  const unauth = status?.status === 401;

  const dirty = useMemo(() => {
    const a = (data?.origins ?? []).slice().sort().join("|");
    const b = draft.slice().sort().join("|");
    return a !== b;
  }, [data?.origins, draft]);

  function addEntry() {
    const v = newEntry.trim();
    if (!v) return;
    if (!looksLikeOrigin(v)) {
      setFlash({ kind: "err", msg: "Use scheme://host[:port], for example https://app.acme.com." });
      return;
    }
    if (draft.includes(v)) {
      setFlash({ kind: "err", msg: "That origin is already in the list." });
      return;
    }
    setDraft([...draft, v]);
    setNewEntry("");
    setFlash(null);
  }

  function removeEntry(idx: number) {
    setDraft(draft.filter((_, i) => i !== idx));
  }

  async function save() {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/cors-origins", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ origins: draft }),
      });
      const body = await res.json();
      if (!res.ok) {
        setFlash({
          kind: "err",
          msg: typeof body?.detail === "string" ? body.detail : `Save failed (${res.status}).`,
        });
        return;
      }
      setFlash({
        kind: "ok",
        msg: body.origins.length
          ? `Saved. ${body.origins.length} origin${body.origins.length === 1 ? "" : "s"} allowed.`
          : "Saved. Browser-origin enforcement disabled.",
      });
      await mutate(body, { revalidate: false });
    } catch (e) {
      setFlash({ kind: "err", msg: e instanceof Error ? e.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Globe size={18} weight="duotone" /> Browser origin allowlist
          </h2>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Restrict which web origins can call this workspace from a browser.
            Server to server callers that omit the Origin header are not
            affected. Leave empty to disable.
          </p>
        </div>
      </header>

      {unauth ? (
        <p className="text-sm text-zinc-500">Sign in to manage this setting.</p>
      ) : forbidden ? (
        <p className="text-sm text-zinc-500">Workspace admin role required.</p>
      ) : isLoading ? (
        <div className="space-y-2" aria-busy>
          <div className="h-8 animate-pulse rounded bg-zinc-100 dark:bg-zinc-900" />
          <div className="h-8 animate-pulse rounded bg-zinc-100 dark:bg-zinc-900" />
        </div>
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          Could not load origin allowlist.
        </p>
      ) : (
        <>
          <ul className="mb-3 divide-y divide-zinc-100 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {draft.length === 0 ? (
              <li className="px-3 py-4 text-sm text-zinc-500">
                No origins configured. Browser-origin enforcement is off for
                this workspace.
              </li>
            ) : (
              draft.map((origin, i) => (
                <li
                  key={`${origin}-${i}`}
                  className="flex items-center justify-between gap-3 px-3 py-2"
                >
                  <code className="break-all text-sm">{origin}</code>
                  <button
                    type="button"
                    onClick={() => removeEntry(i)}
                    className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    aria-label={`Remove ${origin}`}
                  >
                    <Trash size={14} weight="duotone" /> Remove
                  </button>
                </li>
              ))
            )}
          </ul>

          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              value={newEntry}
              onChange={(e) => setNewEntry(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addEntry();
                }
              }}
              placeholder="https://app.acme.com"
              className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              aria-label="Add browser origin"
            />
            <button
              type="button"
              onClick={addEntry}
              className="inline-flex items-center justify-center gap-1 rounded-md border border-zinc-200 px-3 py-2 text-sm hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900"
            >
              <Plus size={14} weight="duotone" /> Add
            </button>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              onClick={save}
              disabled={busy || !dirty}
              className="inline-flex items-center gap-1 rounded-md bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
            >
              <FloppyDisk size={16} weight="duotone" />{" "}
              {busy ? "Saving" : "Save changes"}
            </button>
            {flash ? (
              <span
                className={
                  "text-xs " +
                  (flash.kind === "ok"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-600 dark:text-red-400")
                }
                role="status"
              >
                {flash.msg}
              </span>
            ) : null}
          </div>
          <p className="mt-3 text-xs text-zinc-500">
            Changes take effect on the next request. Saving requires a recent
            MFA verification.
          </p>
        </>
      )}
    </section>
  );
}
