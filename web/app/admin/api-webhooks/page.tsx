"use client";

// Enterprise webhook admin: subscriptions + delivery log + replay, backed
// by the FastAPI /v1/webhooks endpoints (not the legacy file store). The
// API service enforces admin role, MFA step-up, tenant scoping, and
// audit logging; this page is the operator-facing surface for them.

import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  WebhooksLogo,
  Plus,
  ShieldCheck,
  Warning,
  Copy,
  Check,
  ArrowsClockwise,
  Trash,
  ArrowSquareOut,
  Pulse,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Subscription = {
  id: string;
  tenant_id: string;
  url: string;
  description: string | null;
  events: string[];
  active: boolean;
  created_at: string;
  created_by: string | null;
  revoked_at: string | null;
  last_delivery_at: string | null;
  success_count: number;
  failure_count: number;
};

type Delivery = {
  id: string;
  subscription_id: string;
  event: string;
  url: string;
  status: "success" | "failed";
  attempt: number;
  http_status: number | null;
  error: string | null;
  latency_ms: number | null;
  created_at: string;
};

type ListResp = { webhooks: Subscription[]; allowed_events: string[] };
type DeliveriesResp = { deliveries: Delivery[] };

function fmt(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function StatusPill({ s }: { s: "success" | "failed" }) {
  const ok = s === "success";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
        ok
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
          : "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
      }`}
    >
      {ok ? <ShieldCheck size={12} weight="duotone" /> : <Warning size={12} weight="duotone" />}
      {s}
    </span>
  );
}

export default function ApiWebhooksPage() {
  const subs = useSWR<ListResp>("/api/v1-webhooks", fetcher);
  const deliveries = useSWR<DeliveriesResp>(
    "/api/v1-webhooks/deliveries/recent?limit=50",
    fetcher,
    { refreshInterval: 5000 },
  );

  const [showCreate, setShowCreate] = useState(false);
  const [createUrl, setCreateUrl] = useState("");
  const [createEvents, setCreateEvents] = useState<string[]>([
    "classify.completed",
  ]);
  const [createDesc, setCreateDesc] = useState("");
  const [createErr, setCreateErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const events = subs.data?.allowed_events ?? [
    "classify.completed",
    "classify.failed",
    "*",
  ];

  const handleCreate = useCallback(async () => {
    setCreateErr(null);
    if (!createUrl.trim()) {
      setCreateErr("URL is required.");
      return;
    }
    if (createEvents.length === 0) {
      setCreateErr("Pick at least one event.");
      return;
    }
    setCreating(true);
    try {
      const r = await fetch("/api/v1-webhooks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          url: createUrl.trim(),
          events: createEvents,
          description: createDesc.trim() || null,
        }),
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || r.statusText);
      }
      const body = await r.json();
      setRevealedSecret(body.secret);
      setCreateUrl("");
      setCreateDesc("");
      setCreateEvents(["classify.completed"]);
      setShowCreate(false);
      subs.mutate();
    } catch (e: unknown) {
      setCreateErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }, [createUrl, createEvents, createDesc, subs]);

  const handleRevoke = useCallback(
    async (id: string) => {
      if (!confirm(`Revoke webhook ${id}? Deliveries will stop immediately.`)) return;
      setBusy(id);
      try {
        const r = await fetch(`/api/v1-webhooks/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        if (!r.ok) throw new Error(await r.text());
        subs.mutate();
      } catch (e) {
        alert(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
      }
    },
    [subs],
  );

  const handleReplay = useCallback(
    async (deliveryId: string) => {
      setBusy(deliveryId);
      try {
        const r = await fetch(
          `/api/v1-webhooks/deliveries/${encodeURIComponent(deliveryId)}/replay`,
          { method: "POST" },
        );
        if (!r.ok) throw new Error(await r.text());
        deliveries.mutate();
      } catch (e) {
        alert(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
      }
    },
    [deliveries],
  );

  const denied = subs.error && (subs.error as { status?: number }).status === 403;
  const needsTenant =
    subs.error && (subs.error as { status?: number }).status === 422;

  const subList = subs.data?.webhooks ?? [];
  const delivList = deliveries.data?.deliveries ?? [];

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <WebhooksLogo size={28} weight="duotone" className="text-indigo-500" />
            API webhooks
          </h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Server-to-server delivery from the API service. Signed with HMAC SHA-256,
            retried with exponential backoff, scoped to this workspace.
          </p>
        </div>
        {!denied && !needsTenant && (
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
          >
            <Plus size={16} weight="bold" /> New subscription
          </button>
        )}
      </header>

      {denied && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
          You need the admin role on this workspace to manage webhooks.
        </div>
      )}

      {needsTenant && (
        <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
          Webhooks are scoped per workspace. Select or create a workspace first.
        </div>
      )}

      {revealedSecret && (
        <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900/40 dark:bg-emerald-950/30">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-emerald-900 dark:text-emerald-200">
                Save this signing secret now
              </div>
              <p className="mt-1 text-xs text-emerald-800/80 dark:text-emerald-300/80">
                It will not be shown again. Receivers verify each delivery with{" "}
                <code className="font-mono">HMAC-SHA256(SHA256(secret), body)</code>.
              </p>
            </div>
            <button
              onClick={() => {
                navigator.clipboard.writeText(revealedSecret);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-white px-2.5 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-50 dark:border-emerald-800/50 dark:bg-zinc-900 dark:text-emerald-200"
            >
              {copied ? <Check size={12} weight="bold" /> : <Copy size={12} weight="bold" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className="mt-3 break-all rounded bg-white p-2 font-mono text-xs text-emerald-900 dark:bg-zinc-950 dark:text-emerald-200">
            {revealedSecret}
          </div>
          <button
            onClick={() => setRevealedSecret(null)}
            className="mt-3 text-xs text-emerald-700 underline dark:text-emerald-300"
          >
            I have saved it, dismiss
          </button>
        </div>
      )}

      {showCreate && (
        <div className="mb-8 rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm sm:col-span-2">
              <span className="font-medium text-zinc-700 dark:text-zinc-300">URL</span>
              <input
                value={createUrl}
                onChange={(e) => setCreateUrl(e.target.value)}
                placeholder="https://api.example.com/hooks/shotclassify"
                className="rounded-md border border-zinc-200 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-800 dark:bg-zinc-900"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm sm:col-span-2">
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                Description
              </span>
              <input
                value={createDesc}
                onChange={(e) => setCreateDesc(e.target.value)}
                placeholder="prod ingest pipeline"
                className="rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900"
              />
            </label>
            <fieldset className="flex flex-col gap-1 text-sm sm:col-span-2">
              <legend className="font-medium text-zinc-700 dark:text-zinc-300">
                Events
              </legend>
              <div className="mt-1 flex flex-wrap gap-2">
                {events.map((ev) => {
                  const on = createEvents.includes(ev);
                  return (
                    <button
                      key={ev}
                      type="button"
                      onClick={() =>
                        setCreateEvents((arr) =>
                          on ? arr.filter((e) => e !== ev) : [...arr, ev],
                        )
                      }
                      className={`rounded-full border px-3 py-1 text-xs font-medium ${
                        on
                          ? "border-indigo-500 bg-indigo-50 text-indigo-700 dark:border-indigo-500/60 dark:bg-indigo-950/40 dark:text-indigo-300"
                          : "border-zinc-200 bg-white text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
                      }`}
                    >
                      {ev}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          </div>
          {createErr && (
            <div className="mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-300">
              {createErr}
            </div>
          )}
          <div className="mt-4 flex items-center gap-2">
            <button
              onClick={handleCreate}
              disabled={creating}
              className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create subscription"}
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="rounded-md px-3 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <section className="mb-10">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Subscriptions
        </h2>
        {subs.isLoading && !subs.data ? (
          <div className="space-y-2">
            <div className="h-14 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
            <div className="h-14 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
          </div>
        ) : subList.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-300 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-950">
            <WebhooksLogo
              size={32}
              weight="duotone"
              className="mx-auto mb-2 text-zinc-400"
            />
            No subscriptions yet. Create one to start receiving signed events.
          </div>
        ) : (
          <ul className="space-y-2">
            {subList.map((s) => (
              <li
                key={s.id}
                className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="break-all font-mono text-sm text-zinc-900 dark:text-zinc-100">
                        {s.url}
                      </span>
                      {s.active ? (
                        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                          active
                        </span>
                      ) : (
                        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
                          revoked
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-zinc-500">
                      {s.description ? `${s.description} · ` : ""}
                      {s.events.join(", ")} · created {fmt(s.created_at)}
                      {s.created_by ? ` by ${s.created_by}` : ""}
                    </div>
                    <div className="mt-1 text-xs text-zinc-500">
                      {s.success_count} success · {s.failure_count} failed · last{" "}
                      {fmt(s.last_delivery_at)}
                    </div>
                  </div>
                  {s.active && (
                    <button
                      onClick={() => handleRevoke(s.id)}
                      disabled={busy === s.id}
                      className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900/40 dark:bg-zinc-950 dark:text-rose-300 dark:hover:bg-rose-950/30"
                    >
                      <Trash size={12} weight="bold" /> Revoke
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          <Pulse size={14} weight="duotone" /> Recent deliveries
        </h2>
        {deliveries.isLoading && !deliveries.data ? (
          <div className="h-32 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-900" />
        ) : delivList.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-300 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-950">
            No deliveries in this window. Run a classification to fire one.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900">
                <tr>
                  <th className="px-3 py-2 font-medium">When</th>
                  <th className="px-3 py-2 font-medium">Event</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">HTTP</th>
                  <th className="px-3 py-2 font-medium">Attempts</th>
                  <th className="px-3 py-2 font-medium">Latency</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {delivList.map((d) => (
                  <tr
                    key={d.id}
                    className="border-t border-zinc-100 dark:border-zinc-900"
                  >
                    <td className="px-3 py-2 text-xs text-zinc-500">
                      {fmt(d.created_at)}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{d.event}</td>
                    <td className="px-3 py-2">
                      <StatusPill s={d.status} />
                    </td>
                    <td className="px-3 py-2 text-xs">{d.http_status ?? "—"}</td>
                    <td className="px-3 py-2 text-xs">{d.attempt}</td>
                    <td className="px-3 py-2 text-xs">
                      {d.latency_ms != null ? `${d.latency_ms} ms` : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => handleReplay(d.id)}
                        disabled={busy === d.id}
                        className="inline-flex items-center gap-1 rounded border border-zinc-200 bg-white px-2 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      >
                        <ArrowsClockwise size={12} weight="bold" /> Replay
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
