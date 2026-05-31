"use client";

// Per-tenant webhook egress host allowlist. Entries are exact hostnames
// (hooks.example.com) or leading-dot suffixes (.example.com) that match
// the apex and any subdomain. Tightening the policy takes effect on the
// very next delivery for every existing subscription; the dispatcher
// records a failed delivery whose error names egress blocked and never
// attempts the HTTP call.

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  Plus,
  Trash,
  FloppyDisk,
  Warning,
  CheckCircle,
  Globe,
  Lock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type EgressResponse = {
  tenant_id: string;
  hosts: string[];
  max_hosts: number;
};

type ApiError = Error & { status?: number };

function isProbablyHost(s: string): boolean {
  const v = s.trim().toLowerCase();
  if (!v) return false;
  if (v.includes("*")) return false;
  if (v.includes("..")) return false;
  const candidate = v.startsWith(".") ? v.slice(1) : v;
  return /^[a-z0-9]([a-z0-9\-.]{0,253}[a-z0-9])?$/.test(candidate);
}

export default function WebhookEgressPage() {
  const { data, error, isLoading, mutate } = useSWR<EgressResponse>(
    "/api/settings/security/webhook-egress-hosts",
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
    if (data?.hosts) setDraft(data.hosts);
  }, [data?.hosts]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const dirty = useMemo(() => {
    if (!data?.hosts) return draft.length > 0;
    if (data.hosts.length !== draft.length) return true;
    for (let i = 0; i < draft.length; i += 1) {
      if (data.hosts[i] !== draft[i]) return true;
    }
    return false;
  }, [data?.hosts, draft]);

  const max = data?.max_hosts ?? 64;
  const atCap = draft.length >= max;

  function add() {
    const v = newEntry.trim().toLowerCase();
    if (!v) return;
    if (!isProbablyHost(v)) {
      setFlash({
        kind: "err",
        msg: "Enter a hostname (hooks.example.com) or a leading-dot suffix (.example.com).",
      });
      return;
    }
    if (draft.includes(v)) {
      setFlash({ kind: "err", msg: "Already in the list." });
      return;
    }
    if (atCap) {
      setFlash({ kind: "err", msg: `At most ${max} hosts per workspace.` });
      return;
    }
    setDraft([...draft, v]);
    setNewEntry("");
    setFlash(null);
  }

  function remove(host: string) {
    setDraft(draft.filter((h) => h !== host));
  }

  async function save() {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/settings/security/webhook-egress-hosts", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ hosts: draft }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail ?? body.error ?? `HTTP ${res.status}`);
      }
      await mutate();
      setFlash({
        kind: "ok",
        msg: draft.length
          ? "Allowlist saved. New and existing subscriptions are filtered against this list."
          : "Allowlist cleared. Only the deployment SSRF block applies now.",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFlash({ kind: "err", msg });
    } finally {
      setBusy(false);
    }
  }

  function revert() {
    setDraft(data?.hosts ?? []);
    setFlash(null);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:py-10">
      <header className="mb-6 flex items-start gap-3">
        <ShieldCheck size={28} weight="duotone" className="mt-1 shrink-0" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Webhook egress allowlist
          </h1>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Restrict the hostnames this workspace&apos;s webhooks may post to.
            When the list is empty, only the deployment SSRF block applies
            (private addresses, loopback, link-local, cloud metadata). When
            non-empty, every subscription URL must match. Tightening the policy
            blocks the next delivery for every existing subscription.
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
            <span>
              You need the admin role to view or change the webhook egress
              allowlist.
            </span>
          </div>
        </div>
      )}

      {!unauth && !forbidden && (
        <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-950 sm:p-6">
          {isLoading && !data ? (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-9 w-full animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
              <div className="h-9 w-full animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
              <div className="h-9 w-2/3 animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-2 sm:flex-row">
                <div className="relative flex-1">
                  <Globe
                    size={16}
                    weight="duotone"
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400"
                  />
                  <input
                    type="text"
                    inputMode="url"
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                    value={newEntry}
                    onChange={(e) => setNewEntry(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        add();
                      }
                    }}
                    placeholder="hooks.example.com  or  .example.com"
                    aria-label="Hostname to add"
                    className="h-10 w-full rounded-md border border-neutral-300 bg-white pl-9 pr-3 text-sm outline-none transition focus:border-neutral-500 focus:ring-2 focus:ring-neutral-300 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-500 dark:focus:ring-neutral-700"
                  />
                </div>
                <button
                  type="button"
                  onClick={add}
                  disabled={!newEntry.trim() || atCap}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                >
                  <Plus size={16} weight="bold" />
                  Add
                </button>
              </div>

              <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
                {draft.length} of {max} entries used. Wildcards are not allowed;
                use a leading dot for suffix matches.
              </p>

              <ul className="mt-4 divide-y divide-neutral-200 rounded-md border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
                {draft.length === 0 ? (
                  <li className="px-4 py-6 text-center text-sm text-neutral-500 dark:text-neutral-400">
                    No entries. The deployment SSRF block still rejects private,
                    loopback, link-local, and cloud metadata addresses.
                  </li>
                ) : (
                  draft.map((host) => (
                    <li
                      key={host}
                      className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm"
                    >
                      <span className="break-all font-mono text-[13px]">
                        {host}
                      </span>
                      <button
                        type="button"
                        onClick={() => remove(host)}
                        aria-label={`Remove ${host}`}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-neutral-500 transition hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-950 dark:hover:text-red-300"
                      >
                        <Trash size={16} weight="duotone" />
                      </button>
                    </li>
                  ))
                )}
              </ul>

              <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
                {dirty && (
                  <button
                    type="button"
                    onClick={revert}
                    disabled={busy}
                    className="h-10 rounded-md border border-neutral-300 px-4 text-sm font-medium transition hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
                  >
                    Revert
                  </button>
                )}
                <button
                  type="button"
                  onClick={save}
                  disabled={!dirty || busy}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                >
                  <FloppyDisk size={16} weight="duotone" />
                  {busy ? "Saving" : "Save allowlist"}
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
            </>
          )}
        </section>
      )}
    </div>
  );
}
