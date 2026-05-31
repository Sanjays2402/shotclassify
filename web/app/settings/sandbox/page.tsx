"use client";

import { useMemo, useState } from "react";
import {
  ShieldCheck,
  Eye,
  CheckCircle,
  Warning,
  ArrowRight,
  PlayCircle,
} from "@phosphor-icons/react/dist/ssr";

type BulkResult = {
  ok: boolean;
  dry_run?: true;
  applied?: false;
  action: string;
  requested: number;
  would_affect?: number;
  affected?: number;
  missing: string[];
};

const SUPPORTED = [
  {
    method: "DELETE",
    path: "/v1/workspace/data",
    note: "Workspace-wide erasure. Preview counts without touching data.",
  },
  {
    method: "DELETE",
    path: "/v1/me/data",
    note: "Per-user GDPR erasure for the calling principal.",
  },
  {
    method: "DELETE",
    path: "/v1/history/{id}",
    note: "Single classification delete.",
  },
  {
    method: "POST",
    path: "/v1/history/bulk",
    note: "Bulk delete, pin, tag. Preview how many rows would change.",
  },
  {
    method: "DELETE",
    path: "/v1/saved-views/{id}",
    note: "Personal saved view delete.",
  },
  {
    method: "DELETE",
    path: "/v1/sessions/{id}",
    note: "Revoke a single session.",
  },
  {
    method: "POST",
    path: "/v1/sessions/revoke-all",
    note: "Force logout every session for the caller.",
  },
  {
    method: "POST",
    path: "/v1/sessions/admin/revoke-principal",
    note: "Admin force logout of another principal.",
  },
  {
    method: "DELETE",
    path: "/v1/api-keys/{id}",
    note: "Soft revoke an API key.",
  },
  {
    method: "DELETE",
    path: "/v1/members/{principal}",
    note: "Remove a workspace member.",
  },
  {
    method: "DELETE",
    path: "/v1/invitations/{id}",
    note: "Revoke a pending invitation.",
  },
  {
    method: "DELETE",
    path: "/v1/mfa",
    note: "Disable MFA for the caller.",
  },
];

export default function SandboxPage() {
  const [idsRaw, setIdsRaw] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BulkResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ids = useMemo(
    () =>
      idsRaw
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    [idsRaw],
  );

  async function runPreview() {
    if (ids.length === 0) {
      setError("Paste at least one shot id to preview.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/history/bulk?dry_run=true", {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ ids, action: "delete" }),
      });
      const data = (await res.json()) as BulkResult | { detail?: string };
      if (!res.ok) {
        setError(
          (data as { detail?: string }).detail ?? `Request failed (${res.status})`,
        );
        return;
      }
      setResult(data as BulkResult);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
      <header className="mb-8 flex items-start gap-3">
        <ShieldCheck size={32} weight="duotone" className="mt-1 shrink-0 text-emerald-600" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Sandbox mode</h1>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Every destructive endpoint accepts <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs dark:bg-neutral-800">?dry_run=true</code>.
            The API returns the counts that would change, sets the <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs dark:bg-neutral-800">X-Dry-Run</code> response header,
            and writes an audit row tagged <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs dark:bg-neutral-800">extra.dry_run = true</code>.
            Nothing is mutated.
          </p>
        </div>
      </header>

      <section className="mb-10 rounded-xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-950">
        <div className="mb-3 flex items-center gap-2">
          <PlayCircle size={20} weight="duotone" className="text-blue-600" />
          <h2 className="text-base font-medium">Try a dry-run bulk delete</h2>
        </div>
        <p className="mb-3 text-sm text-neutral-600 dark:text-neutral-400">
          Paste one or more shot ids (comma or whitespace separated). The preview reports how many rows
          would be affected and which ids are missing for your tenant. No data is removed.
        </p>
        <label htmlFor="ids" className="sr-only">Shot ids to preview</label>
        <textarea
          id="ids"
          value={idsRaw}
          onChange={(e) => setIdsRaw(e.target.value)}
          placeholder="abc123, def456"
          rows={3}
          className="w-full resize-y rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-mono shadow-sm focus:border-neutral-500 focus:outline-none focus:ring-1 focus:ring-neutral-500 dark:border-neutral-700 dark:bg-neutral-900"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={runPreview}
            disabled={busy || ids.length === 0}
            className="inline-flex items-center gap-2 rounded-lg bg-neutral-900 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
          >
            <Eye size={16} weight="duotone" />
            {busy ? "Previewing..." : `Preview delete of ${ids.length || 0}`}
          </button>
          {result && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400">
              <CheckCircle size={14} weight="duotone" /> dry_run = true
            </span>
          )}
        </div>

        {error && (
          <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {result && (
          <dl className="mt-4 grid grid-cols-3 gap-3 rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
            <div>
              <dt className="text-xs uppercase tracking-wide text-neutral-500">Requested</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums">{result.requested}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-neutral-500">Would affect</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
                {result.would_affect ?? result.affected ?? 0}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-neutral-500">Missing</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums text-neutral-700 dark:text-neutral-300">
                {result.missing.length}
              </dd>
            </div>
          </dl>
        )}

        {!result && !error && (
          <p className="mt-4 text-xs text-neutral-500">
            Empty state. Paste shot ids above and run a preview to see counts here.
          </p>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-base font-medium">Endpoints that support dry_run</h2>
        <ul className="divide-y divide-neutral-200 overflow-hidden rounded-xl border border-neutral-200 bg-white dark:divide-neutral-800 dark:border-neutral-800 dark:bg-neutral-950">
          {SUPPORTED.map((row) => (
            <li key={`${row.method} ${row.path}`} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
              <span
                className={`inline-flex w-fit shrink-0 items-center rounded px-2 py-0.5 text-xs font-semibold ${
                  row.method === "DELETE"
                    ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
                    : "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                }`}
              >
                {row.method}
              </span>
              <code className="font-mono text-sm text-neutral-900 dark:text-neutral-100">{row.path}</code>
              <span className="text-sm text-neutral-600 dark:text-neutral-400 sm:ml-auto">{row.note}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-10 rounded-xl border border-neutral-200 bg-white p-5 text-sm dark:border-neutral-800 dark:bg-neutral-950">
        <h2 className="mb-2 flex items-center gap-2 text-base font-medium">
          <ArrowRight size={18} weight="duotone" /> curl example
        </h2>
        <pre className="overflow-x-auto rounded-lg bg-neutral-900 p-3 text-xs leading-relaxed text-neutral-100">
{`curl -X POST 'https://api.example.com/v1/history/bulk?dry_run=true' \\
  -H 'authorization: Bearer sk_live_...' \\
  -H 'content-type: application/json' \\
  -d '{"ids":["abc","def"],"action":"delete"}'`}
        </pre>
        <p className="mt-3 text-neutral-600 dark:text-neutral-400">
          A successful preview returns HTTP 200 with <code>dry_run: true</code>, <code>applied: false</code>,
          a <code>would_affect</code> integer, and the <code>X-Dry-Run: true</code> header.
        </p>
      </section>
    </main>
  );
}
