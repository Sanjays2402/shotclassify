"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Broadcast as Webhooks,
  Plus,
  Copy,
  Check,
  Trash,
  Warning,
  Lightning,
  CircleNotch,
  PaperPlaneTilt,
  Pause,
  Play,
  ShieldCheck,
  X,
} from "@phosphor-icons/react/dist/ssr";

type WebhookRow = {
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

function fmtDate(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function WebhooksPage() {
  const [hooks, setHooks] = useState<WebhookRow[] | null>(null);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [revealed, setRevealed] = useState<{
    url: string;
    secret: string;
  } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [allowlist, setAllowlist] = useState<string[] | null>(null);
  const [allowDraft, setAllowDraft] = useState("");
  const [allowBusy, setAllowBusy] = useState(false);
  const [allowMsg, setAllowMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/webhooks?deliveries=1", {
        credentials: "same-origin",
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const j = await r.json();
      setHooks(j.webhooks || []);
      setDeliveries(j.deliveries || []);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || "Failed to load webhooks.");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);

  const loadAllowlist = useCallback(async () => {
    try {
      const r = await fetch("/api/webhooks/allowlist", {
        credentials: "same-origin",
      });
      if (!r.ok) throw new Error(`${r.status}`);
      const j = await r.json();
      setAllowlist(Array.isArray(j?.hostnames) ? j.hostnames : []);
    } catch {
      setAllowlist([]);
    }
  }, []);

  useEffect(() => {
    loadAllowlist();
  }, [loadAllowlist]);

  const saveAllowlist = useCallback(
    async (next: string[]) => {
      setAllowBusy(true);
      setAllowMsg(null);
      try {
        const r = await fetch("/api/webhooks/allowlist", {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ hostnames: next }),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j?.error?.message || `${r.status}`);
        setAllowlist(j.hostnames || []);
        if (Array.isArray(j.rejected) && j.rejected.length > 0) {
          setAllowMsg(`Rejected: ${j.rejected.join(", ")}`);
        } else {
          setAllowMsg("Saved");
          setTimeout(() => setAllowMsg(null), 1500);
        }
      } catch (e: any) {
        setAllowMsg(e?.message || "Save failed");
      } finally {
        setAllowBusy(false);
      }
    },
    [],
  );

  const create = useCallback(async () => {
    const url = newUrl.trim();
    if (!url) {
      setErr("URL is required.");
      return;
    }
    setCreating(true);
    setErr(null);
    try {
      const r = await fetch("/api/webhooks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url, description: newDesc }),
      });
      const j = await r.json();
      if (!r.ok) {
        throw new Error(j?.error?.message || `${r.status} ${r.statusText}`);
      }
      setRevealed({ url: j.webhook.url, secret: j.webhook.secret });
      setNewUrl("");
      setNewDesc("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Could not create webhook.");
    } finally {
      setCreating(false);
    }
  }, [newUrl, newDesc, load]);

  const remove = useCallback(
    async (id: string) => {
      if (!confirm("Delete this webhook? Future events will not be sent.")) return;
      setBusyId(id);
      try {
        const r = await fetch(`/api/webhooks/${id}`, { method: "DELETE" });
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Delete failed.");
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const toggle = useCallback(
    async (id: string, active: boolean) => {
      setBusyId(id);
      try {
        const r = await fetch(`/api/webhooks/${id}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ active }),
        });
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Update failed.");
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const test = useCallback(
    async (id: string) => {
      setBusyId(id);
      try {
        const r = await fetch(`/api/webhooks/${id}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ action: "test" }),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j?.error?.message || `${r.status}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Test fire failed.");
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const copy = useCallback(async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard might be unavailable */
    }
  }, []);

  const summary = useMemo(() => {
    if (!hooks) return null;
    const total = hooks.length;
    const active = hooks.filter((h) => h.active).length;
    const last24h = deliveries.filter(
      (d) => Date.now() - new Date(d.created_at).getTime() < 24 * 3600 * 1000,
    );
    const failed = last24h.filter((d) => d.status === "failed").length;
    return { total, active, last24h: last24h.length, failed };
  }, [hooks, deliveries]);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Webhooks size={22} weight="duotone" />
            <h1 className="h-display text-2xl">Webhooks</h1>
          </div>
          <p className="mt-1 text-sm opacity-70 max-w-xl">
            Get notified when a classification completes. We POST a signed JSON
            payload to your URL and retry up to 4 times with backoff on failure.
          </p>
        </div>
        {summary && (
          <div className="flex flex-wrap gap-3 text-xs">
            <Stat label="active" value={`${summary.active}/${summary.total}`} />
            <Stat label="deliveries 24h" value={summary.last24h.toString()} />
            <Stat
              label="failed 24h"
              value={summary.failed.toString()}
              warn={summary.failed > 0}
            />
          </div>
        )}
      </header>

      {err && (
        <div
          className="flex items-start gap-2 rounded border px-3 py-2 text-sm"
          style={{ borderColor: "var(--color-rule)", background: "#fff5f5" }}
          role="alert"
        >
          <Warning size={16} weight="duotone" />
          <span>{err}</span>
        </div>
      )}

      {revealed && (
        <div
          className="rounded border p-4 space-y-2"
          style={{
            borderColor: "var(--color-rule)",
            background: "var(--color-chalk)",
          }}
        >
          <div className="flex items-center gap-2 text-sm font-medium">
            <Lightning size={16} weight="duotone" />
            Save this signing secret. It will not be shown again.
          </div>
          <div className="text-xs opacity-70">{revealed.url}</div>
          <div className="flex items-center gap-2">
            <code className="font-mono text-xs break-all flex-1 rounded bg-black/5 px-2 py-1">
              {revealed.secret}
            </code>
            <button
              type="button"
              className="btn btn-secondary text-xs px-2 py-1"
              onClick={() => copy("secret", revealed.secret)}
              aria-label="Copy signing secret"
            >
              {copied === "secret" ? (
                <Check size={14} weight="bold" />
              ) : (
                <Copy size={14} weight="duotone" />
              )}
              <span className="ml-1">
                {copied === "secret" ? "Copied" : "Copy"}
              </span>
            </button>
            <button
              type="button"
              className="btn btn-secondary text-xs px-2 py-1"
              onClick={() => setRevealed(null)}
            >
              Dismiss
            </button>
          </div>
          <p className="text-xs opacity-70">
            Use this to verify the{" "}
            <code className="font-mono">x-shotclassify-signature</code> header
            (HMAC-SHA256 over the raw request body).
          </p>
        </div>
      )}

      <section
        className="rounded border p-4 space-y-3"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <div className="flex items-center gap-2 text-sm font-medium">
          <Plus size={16} weight="bold" />
          Add endpoint
        </div>
        <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
          <input
            type="url"
            placeholder="https://example.com/hooks/shotclassify"
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            className="rounded border px-3 py-2 text-sm font-mono"
            style={{ borderColor: "var(--color-rule)" }}
            aria-label="Webhook URL"
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            className="rounded border px-3 py-2 text-sm"
            style={{ borderColor: "var(--color-rule)" }}
            maxLength={200}
            aria-label="Webhook description"
          />
          <button
            type="button"
            onClick={create}
            disabled={creating || !newUrl.trim()}
            className="btn btn-primary text-sm px-4 py-2 disabled:opacity-50"
          >
            {creating ? (
              <CircleNotch size={14} className="animate-spin" />
            ) : (
              <Plus size={14} weight="bold" />
            )}
            <span className="ml-1">{creating ? "Creating" : "Create"}</span>
          </button>
        </div>
        <p className="text-xs opacity-60">
          Subscribed event: <code className="font-mono">classify.completed</code>
        </p>
      </section>

      <section
        className="rounded border p-4 space-y-3"
        style={{ borderColor: "var(--color-rule)" }}
        aria-label="Outbound delivery safety"
      >
        <div className="flex items-center gap-2 text-sm font-medium">
          <ShieldCheck size={16} weight="duotone" />
          Outbound delivery safety
        </div>
        <p className="text-xs opacity-70 max-w-2xl">
          Deliveries are blocked when the URL resolves to a loopback, link-local,
          private, multicast, broadcast, or cloud metadata address. Cloud
          metadata addresses (169.254.169.254 and friends) can never be
          overridden. Add a hostname below to permit private destinations on
          your network.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {(allowlist || []).map((h) => (
            <span
              key={h}
              className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-mono"
              style={{ borderColor: "var(--color-rule)" }}
            >
              {h}
              <button
                type="button"
                aria-label={`Remove ${h} from allowlist`}
                className="opacity-60 hover:opacity-100"
                disabled={allowBusy}
                onClick={() =>
                  saveAllowlist((allowlist || []).filter((x) => x !== h))
                }
              >
                <X size={12} weight="bold" />
              </button>
            </span>
          ))}
          {allowlist !== null && allowlist.length === 0 && (
            <span className="text-xs opacity-60">No exceptions.</span>
          )}
        </div>
        <div className="grid gap-2 md:grid-cols-[1fr_auto]">
          <input
            type="text"
            placeholder="internal-hook.corp.lan"
            value={allowDraft}
            onChange={(e) => setAllowDraft(e.target.value)}
            className="rounded border px-3 py-2 text-sm font-mono"
            style={{ borderColor: "var(--color-rule)" }}
            aria-label="Hostname to allow"
          />
          <button
            type="button"
            className="btn btn-secondary text-sm px-4 py-2 disabled:opacity-50"
            disabled={allowBusy || !allowDraft.trim()}
            onClick={async () => {
              const v = allowDraft.trim().toLowerCase();
              if (!v) return;
              const next = Array.from(
                new Set([...(allowlist || []), v]),
              );
              await saveAllowlist(next);
              setAllowDraft("");
            }}
          >
            <Plus size={14} weight="bold" />
            <span className="ml-1">Allow hostname</span>
          </button>
        </div>
        {allowMsg && (
          <p className="text-xs opacity-70" role="status">{allowMsg}</p>
        )}
      </section>

      <section>
        <h2 className="h-display text-base mb-3">Endpoints</h2>
        {hooks === null ? (
          <div className="space-y-2" aria-hidden>
            {[0, 1].map((i) => (
              <div
                key={i}
                className="h-20 rounded border animate-pulse bg-black/[0.03]"
                style={{ borderColor: "var(--color-rule)" }}
              />
            ))}
          </div>
        ) : hooks.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="space-y-2">
            {hooks.map((h) => (
              <li
                key={h.id}
                className="rounded border p-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
                style={{ borderColor: "var(--color-rule)" }}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <code className="font-mono text-sm truncate max-w-full">
                      {h.url}
                    </code>
                    {h.active ? (
                      <span
                        className="eyebrow"
                        style={{ color: "var(--color-felt)" }}
                      >
                        active
                      </span>
                    ) : (
                      <span className="eyebrow opacity-60">paused</span>
                    )}
                  </div>
                  {h.description && (
                    <div className="text-xs opacity-70 mt-0.5">
                      {h.description}
                    </div>
                  )}
                  <div className="text-xs opacity-60 mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    <span>secret {h.secret_prefix}…</span>
                    <span>created {fmtDate(h.created_at)}</span>
                    <span>last {fmtDate(h.last_delivery_at)}</span>
                    <span>
                      {h.success_count} ok · {h.failure_count} failed
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Link
                    href={`/webhooks/${encodeURIComponent(h.id)}`}
                    className="btn btn-secondary text-xs px-2 py-1"
                    aria-label="View webhook details and delivery log"
                    title="Details"
                  >
                    <span className="hidden sm:inline">Details</span>
                    <span className="sm:hidden">View</span>
                  </Link>
                  <button
                    type="button"
                    className="btn btn-secondary text-xs px-2 py-1"
                    onClick={() => test(h.id)}
                    disabled={busyId === h.id}
                    aria-label="Send test event"
                    title="Send test event"
                  >
                    <PaperPlaneTilt size={14} weight="duotone" />
                    <span className="ml-1 hidden sm:inline">Test</span>
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary text-xs px-2 py-1"
                    onClick={() => toggle(h.id, !h.active)}
                    disabled={busyId === h.id}
                    aria-label={h.active ? "Pause webhook" : "Activate webhook"}
                  >
                    {h.active ? (
                      <Pause size={14} weight="duotone" />
                    ) : (
                      <Play size={14} weight="duotone" />
                    )}
                    <span className="ml-1 hidden sm:inline">
                      {h.active ? "Pause" : "Resume"}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary text-xs px-2 py-1"
                    onClick={() => remove(h.id)}
                    disabled={busyId === h.id}
                    aria-label="Delete webhook"
                  >
                    <Trash size={14} weight="duotone" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="h-display text-base mb-3">Recent deliveries</h2>
        {deliveries.length === 0 ? (
          <p className="text-sm opacity-60">
            No deliveries yet. Send a test event or run a classification.
          </p>
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
                  <th className="px-3 py-2">URL</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Try</th>
                  <th className="px-3 py-2">ms</th>
                  <th className="px-3 py-2">Detail</th>
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
                    <td className="px-3 py-2 font-mono truncate max-w-[220px]">
                      {d.url}
                    </td>
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
                    <td className="px-3 py-2 font-mono">{d.attempt}</td>
                    <td className="px-3 py-2 font-mono">
                      {d.latency_ms ?? "-"}
                    </td>
                    <td className="px-3 py-2 opacity-70">
                      {d.http_status ?? d.error ?? ""}
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

function Stat({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div
      className="rounded border px-3 py-1.5"
      style={{
        borderColor: "var(--color-rule)",
        background: warn ? "#fff5f5" : "transparent",
      }}
    >
      <div className="eyebrow">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      className="rounded border p-6 text-center space-y-2"
      style={{ borderColor: "var(--color-rule)" }}
    >
      <Webhooks size={28} weight="duotone" className="mx-auto opacity-60" />
      <div className="text-sm font-medium">No endpoints yet</div>
      <p className="text-xs opacity-70 max-w-md mx-auto">
        Add a URL above. We will POST a signed JSON payload every time a
        classification finishes. Try it with a free request bin like
        webhook.site to see live deliveries.
      </p>
    </div>
  );
}
