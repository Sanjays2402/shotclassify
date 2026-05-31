"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Broadcast,
  Check,
  CircleNotch,
  Copy,
  Lightning,
  PaperPlaneTilt,
  Warning,
  ArrowClockwise,
} from "@phosphor-icons/react/dist/ssr";

type Webhook = {
  id: string;
  url: string;
  description: string;
  events: string[];
  active: boolean;
  created_at: string;
  last_delivery_at: string | null;
  success_count: number;
  failure_count: number;
  secret_prefix: string;
};

type Delivery = {
  id: string;
  webhook_id: string;
  event: string;
  url: string;
  status: "success" | "failed" | "pending";
  attempt: number;
  http_status: number | null;
  error: string | null;
  latency_ms: number | null;
  created_at: string;
  payload_preview: string;
};

function fmtDate(s: string | null): string {
  if (!s) return "never";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

export default function WebhookDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [hook, setHook] = useState<Webhook | null>(null);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [selected, setSelected] = useState<Delivery | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(`/api/webhooks/${encodeURIComponent(id)}`, {
        cache: "no-store",
      });
      if (res.status === 404) {
        setHook(null);
        setDeliveries([]);
        setError("Webhook not found.");
        return;
      }
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const body = (await res.json()) as {
        webhook: Webhook;
        deliveries: Delivery[];
      };
      setHook(body.webhook);
      setDeliveries(body.deliveries || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load webhook.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const redeliver = useCallback(
    async (deliveryId: string) => {
      setBusyId(deliveryId);
      try {
        const res = await fetch(`/api/webhooks/${encodeURIComponent(id)}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ action: "redeliver", delivery_id: deliveryId }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body?.error?.message || `HTTP ${res.status}`);
        }
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Redeliver failed.");
      } finally {
        setBusyId(null);
      }
    },
    [id, load],
  );

  const test = useCallback(async () => {
    setBusyId("__test");
    try {
      const res = await fetch(`/api/webhooks/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "test" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.error?.message || `HTTP ${res.status}`);
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test failed.");
    } finally {
      setBusyId(null);
    }
  }, [id, load]);

  const copySecretPrefix = useCallback(async () => {
    if (!hook) return;
    try {
      await navigator.clipboard.writeText(hook.secret_prefix);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  }, [hook]);

  const stats = useMemo(() => {
    const total = deliveries.length;
    const ok = deliveries.filter((d) => d.status === "success").length;
    const fail = deliveries.filter((d) => d.status === "failed").length;
    const avgMs =
      deliveries.length === 0
        ? 0
        : Math.round(
            deliveries.reduce((acc, d) => acc + (d.latency_ms || 0), 0) /
              deliveries.length,
          );
    return { total, ok, fail, avgMs };
  }, [deliveries]);

  return (
    <div className="mx-auto max-w-5xl px-4 sm:px-6 py-8 space-y-6">
      <div>
        <Link
          href="/webhooks"
          className="inline-flex items-center gap-1 text-sm opacity-70 hover:opacity-100"
        >
          <ArrowLeft size={14} weight="duotone" />
          All webhooks
        </Link>
      </div>

      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <Broadcast size={20} weight="duotone" />
          <h1 className="h-display text-xl">Webhook detail</h1>
        </div>
        <p className="text-sm opacity-70">
          Every delivery attempt, the signing secret prefix, and a one-click
          replay button for failed deliveries.
        </p>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded border px-3 py-2 text-sm"
          style={{
            borderColor: "var(--color-rule)",
            color: "#b00020",
          }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3" aria-label="Loading">
          <div
            className="h-24 rounded border animate-pulse bg-black/[0.03]"
            style={{ borderColor: "var(--color-rule)" }}
          />
          <div
            className="h-40 rounded border animate-pulse bg-black/[0.03]"
            style={{ borderColor: "var(--color-rule)" }}
          />
        </div>
      ) : !hook ? (
        <div
          className="rounded border p-6 text-sm"
          style={{ borderColor: "var(--color-rule)" }}
        >
          This webhook does not exist or was deleted.{" "}
          <Link href="/webhooks" className="underline">
            Back to webhooks
          </Link>
          .
        </div>
      ) : (
        <>
          <section
            className="rounded border p-4 space-y-3"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-0 flex-1">
                <code className="font-mono text-sm break-all">{hook.url}</code>
                {hook.description && (
                  <div className="text-xs opacity-70 mt-1">
                    {hook.description}
                  </div>
                )}
                <div className="text-xs opacity-60 mt-2 flex flex-wrap gap-x-3 gap-y-1">
                  <span>
                    status{" "}
                    <span style={{ color: hook.active ? "var(--color-felt)" : undefined }}>
                      {hook.active ? "active" : "paused"}
                    </span>
                  </span>
                  <span>events {hook.events.join(", ") || "none"}</span>
                  <span>created {fmtDate(hook.created_at)}</span>
                  <span>last delivery {fmtDate(hook.last_delivery_at)}</span>
                </div>
                <div className="text-xs opacity-60 mt-2 flex items-center gap-2">
                  <span>signing secret prefix</span>
                  <code className="font-mono">{hook.secret_prefix}…</code>
                  <button
                    type="button"
                    className="btn btn-secondary text-xs px-2 py-1"
                    onClick={copySecretPrefix}
                    aria-label="Copy secret prefix"
                  >
                    {copied ? (
                      <Check size={12} weight="bold" />
                    ) : (
                      <Copy size={12} weight="duotone" />
                    )}
                  </button>
                </div>
              </div>
              <button
                type="button"
                className="btn btn-secondary text-xs px-2 py-1 shrink-0"
                onClick={test}
                disabled={busyId === "__test"}
                aria-label="Send test event"
              >
                {busyId === "__test" ? (
                  <CircleNotch size={14} weight="duotone" className="animate-spin" />
                ) : (
                  <PaperPlaneTilt size={14} weight="duotone" />
                )}
                <span className="ml-1">Send test event</span>
              </button>
            </div>

            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 border-t" style={{ borderColor: "var(--color-rule)" }}>
              <Stat label="deliveries" value={stats.total.toString()} />
              <Stat label="succeeded" value={stats.ok.toString()} />
              <Stat label="failed" value={stats.fail.toString()} />
              <Stat label="avg latency" value={`${stats.avgMs}ms`} />
            </dl>
          </section>

          <section>
            <h2 className="h-display text-base mb-3 flex items-center gap-2">
              <Lightning size={16} weight="duotone" />
              Delivery log
            </h2>
            {deliveries.length === 0 ? (
              <div
                className="rounded border p-6 text-sm opacity-70"
                style={{ borderColor: "var(--color-rule)" }}
              >
                No deliveries recorded yet. Send a test event above or run a
                classification with{" "}
                <code className="font-mono">classify.completed</code> subscribed.
              </div>
            ) : (
              <div
                className="rounded border overflow-x-auto"
                style={{ borderColor: "var(--color-rule)" }}
              >
                <table className="w-full text-xs">
                  <thead className="text-left opacity-70">
                    <tr>
                      <th className="px-3 py-2">When</th>
                      <th className="px-3 py-2">Event</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">HTTP</th>
                      <th className="px-3 py-2">Try</th>
                      <th className="px-3 py-2">ms</th>
                      <th className="px-3 py-2">Error</th>
                      <th className="px-3 py-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deliveries.map((d) => (
                      <tr
                        key={d.id}
                        className="border-t"
                        style={{ borderColor: "var(--color-rule)" }}
                      >
                        <td className="px-3 py-2 font-mono whitespace-nowrap">
                          {fmtDate(d.created_at)}
                        </td>
                        <td className="px-3 py-2 font-mono">{d.event}</td>
                        <td className="px-3 py-2">
                          <span
                            className="inline-flex items-center gap-1"
                            style={{
                              color:
                                d.status === "success"
                                  ? "var(--color-felt)"
                                  : "#b00020",
                            }}
                          >
                            {d.status === "success" ? (
                              <Check size={12} weight="bold" />
                            ) : (
                              <Warning size={12} weight="duotone" />
                            )}
                            {d.status}
                          </span>
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {d.http_status ?? "-"}
                        </td>
                        <td className="px-3 py-2 font-mono">{d.attempt}</td>
                        <td className="px-3 py-2 font-mono">
                          {d.latency_ms ?? "-"}
                        </td>
                        <td className="px-3 py-2 opacity-70 max-w-[220px] truncate">
                          {d.error ?? ""}
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          <button
                            type="button"
                            className="btn btn-secondary text-xs px-2 py-1 mr-1"
                            onClick={() => setSelected(d)}
                            aria-label="View payload"
                          >
                            View
                          </button>
                          <button
                            type="button"
                            className="btn btn-secondary text-xs px-2 py-1"
                            onClick={() => redeliver(d.id)}
                            disabled={busyId === d.id}
                            aria-label="Redeliver"
                            title="Replay this delivery"
                          >
                            {busyId === d.id ? (
                              <CircleNotch
                                size={12}
                                weight="duotone"
                                className="animate-spin"
                              />
                            ) : (
                              <ArrowClockwise size={12} weight="duotone" />
                            )}
                            <span className="ml-1 hidden sm:inline">Replay</span>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {selected && (
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Delivery payload"
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
              onClick={() => setSelected(null)}
            >
              <div
                className="bg-white rounded border max-w-2xl w-full p-4 space-y-3 max-h-[80vh] overflow-auto"
                style={{ borderColor: "var(--color-rule)" }}
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between">
                  <h3 className="h-display text-base">Payload preview</h3>
                  <button
                    type="button"
                    onClick={() => setSelected(null)}
                    className="text-sm opacity-70 hover:opacity-100"
                  >
                    Close
                  </button>
                </div>
                <div className="text-xs opacity-70">
                  Delivery <code className="font-mono">{selected.id}</code> ·{" "}
                  {fmtDate(selected.created_at)} ·{" "}
                  {selected.http_status ?? selected.error ?? "no response"}
                </div>
                <pre className="text-xs font-mono whitespace-pre-wrap break-all bg-black/[0.03] p-3 rounded border" style={{ borderColor: "var(--color-rule)" }}>
                  {selected.payload_preview || "(empty)"}
                </pre>
                <p className="text-xs opacity-60">
                  Only the first 240 characters of the body are stored. Use your
                  receiver logs for the full payload.
                </p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="eyebrow opacity-70">{label}</dt>
      <dd className="font-mono text-sm">{value}</dd>
    </div>
  );
}
