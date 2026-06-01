"use client";

// Per-tenant SIEM audit sinks. Register an HTTPS endpoint and we forward
// every audit row (who did what, when, from where) to it with an HMAC
// signature so Splunk / Datadog / Sumo Logic / any HTTPS log collector
// can verify authenticity. The plaintext signing secret is shown exactly
// once at create time, matching the API-key and webhook UX.

import { useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  Plus,
  Trash,
  Warning,
  CheckCircle,
  Broadcast,
  PaperPlaneTilt,
  Copy,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Sink = {
  id: string;
  tenant_id: string;
  url: string;
  description: string | null;
  active: boolean;
  created_at: string | null;
  created_by: string | null;
  revoked_at: string | null;
  last_delivery_at: string | null;
  last_status: string | null;
  last_error: string | null;
  success_count: number;
  failure_count: number;
};

type ListResponse = { sinks: Sink[] };
type ApiError = Error & { status?: number };

function isHttpsUrl(s: string): boolean {
  const v = s.trim();
  if (!v || v.length > 1024) return false;
  try {
    const u = new URL(v);
    return u.protocol === "https:" || u.protocol === "http:";
  } catch {
    return false;
  }
}

function relTime(iso: string | null): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "never";
  const secs = Math.max(1, Math.round((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

export default function AuditSinksPage() {
  const { data, error, isLoading, mutate } = useSWR<ListResponse>(
    "/api/settings/security/audit-sinks",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );
  const [newSecret, setNewSecret] = useState<{ id: string; secret: string } | null>(
    null,
  );

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;
  const sinks = data?.sinks ?? [];

  async function create() {
    if (!isHttpsUrl(url)) {
      setFlash({ kind: "err", msg: "Enter a full http(s) URL." });
      return;
    }
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/settings/security/audit-sinks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ url: url.trim(), description: description.trim() || null }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setFlash({ kind: "err", msg: body?.detail || `${r.status} ${r.statusText}` });
        return;
      }
      setNewSecret({ id: body.id, secret: body.secret });
      setUrl("");
      setDescription("");
      mutate();
      setFlash({ kind: "ok", msg: "Sink registered. Copy the signing secret now." });
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    if (!confirm("Revoke this audit sink? It will stop receiving events immediately.")) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/settings/security/audit-sinks/${encodeURIComponent(id)}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setFlash({ kind: "err", msg: body?.detail || `${r.status} ${r.statusText}` });
        return;
      }
      mutate();
      setFlash({ kind: "ok", msg: "Sink revoked." });
    } finally {
      setBusy(false);
    }
  }

  async function fireTest(id: string) {
    setBusy(true);
    try {
      const r = await fetch(`/api/settings/security/audit-sinks/${encodeURIComponent(id)}`, {
        method: "POST",
        credentials: "same-origin",
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setFlash({ kind: "err", msg: body?.detail || `${r.status} ${r.statusText}` });
        return;
      }
      mutate();
      const ok = body?.last_status && /^2\d\d$/.test(String(body.last_status));
      setFlash({
        kind: ok ? "ok" : "err",
        msg: ok
          ? `Probe delivered (HTTP ${body.last_status}).`
          : `Probe failed: ${body.last_status ?? "unknown"}${body.last_error ? " — " + body.last_error : ""}`,
      });
    } finally {
      setBusy(false);
    }
  }

  if (unauth) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-xl font-semibold">Audit sinks</h1>
        <p className="mt-3 text-sm text-zinc-600">Sign in to manage audit sinks.</p>
      </main>
    );
  }
  if (forbidden) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-xl font-semibold">Audit sinks</h1>
        <p className="mt-3 text-sm text-zinc-600">
          You need workspace admin role to manage audit sinks.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:py-10">
      <header className="flex items-start gap-3">
        <ShieldCheck size={28} weight="duotone" className="mt-1 text-zinc-500" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Audit sinks</h1>
          <p className="mt-1 text-sm text-zinc-600">
            Forward every audit event from this workspace to your SIEM. We sign each
            delivery with HMAC-SHA256 so the receiver can verify authenticity.
          </p>
        </div>
      </header>

      <section className="mt-8 rounded-lg border border-zinc-200 bg-white p-5">
        <h2 className="text-sm font-medium text-zinc-800">Register a sink</h2>
        <p className="mt-1 text-xs text-zinc-500">
          We POST one JSON event per audit row to this URL. Use https in production.
        </p>
        <div className="mt-4 grid gap-3">
          <label className="block">
            <span className="text-xs font-medium text-zinc-600">Endpoint URL</span>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://collector.example.com/audit"
              className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-zinc-600">Description (optional)</span>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="splunk prod"
              maxLength={255}
              className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200"
            />
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={create}
              disabled={busy || !isHttpsUrl(url)}
              className="inline-flex items-center gap-2 rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
            >
              <Plus size={16} weight="bold" />
              Add sink
            </button>
          </div>
        </div>
      </section>

      {newSecret && (
        <section className="mt-6 rounded-lg border border-amber-300 bg-amber-50 p-4">
          <div className="flex items-start gap-2">
            <Warning size={18} weight="duotone" className="mt-0.5 text-amber-700" />
            <div className="flex-1">
              <div className="text-sm font-medium text-amber-900">
                Copy this signing secret now. It will not be shown again.
              </div>
              <div className="mt-2 flex items-center gap-2">
                <code className="block flex-1 overflow-x-auto rounded border border-amber-300 bg-white px-2 py-1.5 font-mono text-xs">
                  {newSecret.secret}
                </code>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard?.writeText(newSecret.secret);
                    setFlash({ kind: "ok", msg: "Copied." });
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
                >
                  <Copy size={14} weight="bold" />
                  Copy
                </button>
              </div>
              <p className="mt-2 text-xs text-amber-800">
                Receivers verify each request by recomputing{" "}
                <code className="font-mono">HMAC-SHA256(sha256(secret), body)</code>{" "}
                and comparing to <code className="font-mono">X-Shotclassify-Audit-Signature</code>.
              </p>
              <button
                type="button"
                onClick={() => setNewSecret(null)}
                className="mt-3 text-xs font-medium text-amber-900 underline underline-offset-2"
              >
                Dismiss
              </button>
            </div>
          </div>
        </section>
      )}

      {flash && (
        <div
          className={`mt-4 flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
            flash.kind === "ok"
              ? "border-emerald-300 bg-emerald-50 text-emerald-900"
              : "border-rose-300 bg-rose-50 text-rose-900"
          }`}
          role="status"
        >
          {flash.kind === "ok" ? (
            <CheckCircle size={16} weight="duotone" className="mt-0.5" />
          ) : (
            <Warning size={16} weight="duotone" className="mt-0.5" />
          )}
          <span>{flash.msg}</span>
        </div>
      )}

      <section className="mt-8">
        <h2 className="text-sm font-medium text-zinc-800">Registered sinks</h2>
        {isLoading && (
          <div className="mt-3 space-y-2" aria-busy="true">
            <div className="h-16 animate-pulse rounded-md bg-zinc-100" />
            <div className="h-16 animate-pulse rounded-md bg-zinc-100" />
          </div>
        )}
        {!isLoading && sinks.length === 0 && (
          <div className="mt-3 rounded-md border border-dashed border-zinc-300 bg-zinc-50 p-6 text-center text-sm text-zinc-600">
            <Broadcast size={24} weight="duotone" className="mx-auto text-zinc-400" />
            <p className="mt-2">No sinks yet. Register one above to start forwarding.</p>
          </div>
        )}
        {!isLoading && sinks.length > 0 && (
          <ul className="mt-3 divide-y divide-zinc-200 rounded-lg border border-zinc-200 bg-white">
            {sinks.map((s) => (
              <li key={s.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <code className="truncate font-mono text-xs text-zinc-800">{s.url}</code>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                        s.active
                          ? "bg-emerald-100 text-emerald-800"
                          : "bg-zinc-200 text-zinc-700"
                      }`}
                    >
                      {s.active ? "active" : "revoked"}
                    </span>
                  </div>
                  {s.description && (
                    <div className="mt-1 text-xs text-zinc-600">{s.description}</div>
                  )}
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
                    <span>id {s.id}</span>
                    <span>{s.success_count} ok</span>
                    <span>{s.failure_count} failed</span>
                    <span>last {relTime(s.last_delivery_at)}{s.last_status ? ` (${s.last_status})` : ""}</span>
                  </div>
                  {s.last_error && (
                    <div className="mt-1 truncate text-[11px] text-rose-700">
                      {s.last_error}
                    </div>
                  )}
                </div>
                <div className="flex gap-2 sm:shrink-0">
                  <button
                    type="button"
                    onClick={() => fireTest(s.id)}
                    disabled={busy || !s.active}
                    className="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-800 hover:bg-zinc-50 disabled:opacity-40"
                  >
                    <PaperPlaneTilt size={14} weight="duotone" />
                    Test
                  </button>
                  <button
                    type="button"
                    onClick={() => revoke(s.id)}
                    disabled={busy || !s.active}
                    className="inline-flex items-center gap-1.5 rounded-md border border-rose-300 bg-white px-2.5 py-1.5 text-xs font-medium text-rose-800 hover:bg-rose-50 disabled:opacity-40"
                  >
                    <Trash size={14} weight="duotone" />
                    Revoke
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8 rounded-lg border border-zinc-200 bg-zinc-50 p-4 text-xs text-zinc-700">
        <div className="font-medium text-zinc-800">Verifying a delivery</div>
        <pre className="mt-2 overflow-x-auto rounded bg-white p-3 font-mono text-[11px] text-zinc-800">{`key      = sha256(plaintext_secret)
expected = hmac_sha256(key, raw_request_body)
header   = X-Shotclassify-Audit-Signature
ok       = constant_time_eq(expected, header)`}</pre>
      </section>
    </main>
  );
}
