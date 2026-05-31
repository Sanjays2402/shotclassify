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
    </div>
  );
}
