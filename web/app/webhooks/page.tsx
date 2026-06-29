"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Skeleton } from "@/components/Skeleton";
import { EmptyState as FilterEmptyState } from "@/components/EmptyState";
import { emptyCopyForList } from "@/lib/empty-state";
import { WebhookDeliveryBreadcrumb } from "@/components/WebhookDeliveryBreadcrumb";
import CopyDeliveryLinkButton from "@/components/CopyDeliveryLinkButton";
import DeliveryExportMenu from "@/components/DeliveryExportMenu";
import {
  readDeliveryFilterFromUrl,
  writeDeliveryFilterToUrl,
} from "@/lib/webhook-delivery-url";
import {
  isRadioNavKey,
  radioNavIndex,
  radioTabbableIndex,
} from "@/lib/radio-group";
import { deliveryRelativeLabel } from "@/lib/delivery-when";
import { toast } from "@/lib/toast-store";
import {
  canRetryDelivery,
  retryButtonLabel,
  retryAriaLabel,
  retryToast,
} from "@/lib/delivery-retry";
import {
  filterDeliveries,
  distinctDeliveryEvents,
  distinctEventCountLabel,
  deliveryStatusLabel,
  deliveryFilterCountLabel,
  deliveryStatusCounts,
  statusSwatchAria,
  DELIVERY_STATUSES,
  type WebhookDeliveryFilterKey,
} from "@/lib/webhook-delivery-chips";
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
  DotsThreeOutline,
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

// Swatch colours for the status legend (F101). Felt-green for success matches
// the table's status column; red for failed; amber for in-flight pending.
const STATUS_SWATCH: Record<string, string> = {
  success: "var(--color-felt)",
  failed: "#b00020",
  pending: "#b45309",
};

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
  // Recent-deliveries filter (F92): triage the delivery log by status
  // (success / failed / pending) and event name. "all" means no constraint.
  const [statusFilter, setStatusFilter] = useState("all");
  const [eventFilter, setEventFilter] = useState("all");
  // Wall clock for the deliveries' relative-time labels (F129). Refreshed on a
  // slow interval so "3m ago" stays honest without re-rendering constantly.
  // The table only renders after the async fetch resolves, so this never
  // mismatches between SSR and the client.
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Persist the deliveries filter to the URL query (F103) so a reload -- or a
  // shared link -- keeps the triage view. Read once on mount (the page has no
  // router/searchParams, so we read window.location directly), then mirror
  // every change back via history.replaceState. The guard ref keeps the
  // write-effect from clobbering the URL before the initial read has applied,
  // and stops a redundant replaceState on the very first render.
  const filterHydrated = useRef(false);
  useEffect(() => {
    const seed = readDeliveryFilterFromUrl();
    if (typeof seed.status === "string") setStatusFilter(seed.status);
    if (typeof seed.event === "string") setEventFilter(seed.event);
    filterHydrated.current = true;
  }, []);
  useEffect(() => {
    if (!filterHydrated.current) return;
    writeDeliveryFilterToUrl({ status: statusFilter, event: eventFilter });
  }, [statusFilter, eventFilter]);

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

  // Inline retry for a failed delivery (F147): which delivery id is mid-POST,
  // so only that row spins. Fires action=redeliver, then refreshes the table
  // and toasts the outcome -- the new attempt appears on the next load.
  const [retrying, setRetrying] = useState<string | null>(null);
  const onRetryDelivery = useCallback(
    async (d: Delivery) => {
      if (!canRetryDelivery(d) || retrying) return;
      setRetrying(d.id);
      try {
        const r = await fetch(`/api/webhooks/${encodeURIComponent(d.webhook_id)}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ action: "redeliver", delivery_id: d.id }),
        });
        const j = await r.json().catch(() => null);
        const t = retryToast(r.ok, d.event, j?.error?.message);
        if (t.kind === "success") toast.success(t.text);
        else toast.error(t.text);
        await load();
      } catch (e: any) {
        const t = retryToast(false, d.event, e?.message);
        toast.error(t.text);
      } finally {
        setRetrying(null);
      }
    },
    [retrying, load],
  );

  // Tick the relative-time clock every 30s so the deliveries' "Nm ago" labels
  // (F129) age without waiting on the next data fetch. Cheap -- one setState.
  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

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

  // Distinct event names actually present, for the event <select> (F92) --
  // built from the data so a newly-subscribed event shows up automatically.
  const eventOptions = useMemo(
    () => distinctDeliveryEvents(deliveries),
    [deliveries],
  );

  // Live per-status tallies for the legend swatch row (F101) -- always the
  // three known statuses in a stable order, counts read off the full list.
  const statusCounts = useMemo(
    () => deliveryStatusCounts(deliveries),
    [deliveries],
  );

  // Toggle a status swatch: clicking the active status clears the filter,
  // clicking another sets it -- so the legend doubles as a one-click filter.
  const toggleStatusFilter = useCallback((status: string) => {
    setStatusFilter((cur) => (cur === status ? "all" : status));
  }, []);

  // Status legend as a true ARIA radio-group (F128): Arrow keys move the
  // selection AND focus between swatches, only the active one is tabbable
  // (roving tabindex). The math lives in lib/radio-group; here we map the
  // active filter to an index, step it, then commit + move DOM focus.
  const statusRadioRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const onStatusRadioKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!isRadioNavKey(e.key)) return;
      e.preventDefault();
      const idx = statusCounts.findIndex((s) => s.status === statusFilter);
      const next = radioNavIndex(idx, statusCounts.length, e.key);
      if (next == null) return;
      setStatusFilter(statusCounts[next].status);
      statusRadioRefs.current[next]?.focus();
    },
    [statusCounts, statusFilter],
  );

  // The delivery log narrowed by the active status + event filter (F92).
  const filteredDeliveries = useMemo(
    () =>
      filterDeliveries(deliveries, {
        status: statusFilter,
        event: eventFilter,
      }),
    [deliveries, statusFilter, eventFilter],
  );

  const deliveryFilterState = useMemo(
    () => ({ status: statusFilter, event: eventFilter }),
    [statusFilter, eventFilter],
  );

  // Body copy for the filtered-empty deliveries state (F108). Reuses
  // emptyCopyForList so the "Active: ..." summary reads like the shots empty
  // state -- we map the deliveries filter onto its category/tag slots (status
  // as the class, event as the tag) purely to drive the shared phrasing.
  const deliveryEmptyBody = useMemo(
    () =>
      emptyCopyForList("deliveries", {
        category:
          statusFilter !== "all" ? deliveryStatusLabel(statusFilter) : null,
        tag: eventFilter !== "all" ? eventFilter : null,
      }).body,
    [statusFilter, eventFilter],
  );

  // Clear a single delivery filter from a breadcrumb pill.
  const clearDeliveryFilter = useCallback((key: WebhookDeliveryFilterKey) => {
    if (key === "status") setStatusFilter("all");
    else if (key === "event") setEventFilter("all");
  }, []);

  const clearAllDeliveryFilters = useCallback(() => {
    setStatusFilter("all");
    setEventFilter("all");
  }, []);

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
          <div className="space-y-2" aria-label="Loading webhooks" role="status" aria-busy="true">
            {[0, 1].map((i) => (
              <Skeleton key={i} variant="block" height={80} />
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
        <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
          <h2 className="h-display text-base">Recent deliveries</h2>
          {deliveries.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <label className="inline-flex items-center gap-1.5 text-[12px]">
                <span className="eyebrow opacity-70">Status</span>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  aria-label="Filter deliveries by status"
                  className="rounded border px-2 py-1 text-[12px] bg-white"
                  style={{ borderColor: "var(--color-rule)" }}
                >
                  <option value="all">All</option>
                  {DELIVERY_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {deliveryStatusLabel(s)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="inline-flex items-center gap-1.5 text-[12px]">
                <span className="eyebrow opacity-70">
                  Event
                  {/* "N seen" affordance (F110) -- the live distinct-event
                      count so a triager knows the log's breadth without
                      opening the dropdown. Null/hidden when nothing's arrived. */}
                  {(() => {
                    const seen = distinctEventCountLabel(eventOptions);
                    return seen ? (
                      <span className="num opacity-60"> · {seen}</span>
                    ) : null;
                  })()}
                </span>
                <select
                  value={eventFilter}
                  onChange={(e) => setEventFilter(e.target.value)}
                  aria-label="Filter deliveries by event"
                  className="rounded border px-2 py-1 text-[12px] font-mono bg-white"
                  style={{ borderColor: "var(--color-rule)" }}
                  disabled={eventOptions.length === 0}
                >
                  <option value="all">All</option>
                  {eventOptions.map((ev) => (
                    <option key={ev} value={ev}>
                      {ev}
                    </option>
                  ))}
                </select>
              </label>
              {/* Copy link (F113) -- share the exact filtered deliveries view.
                  Reuses the F103 URL serializer; disabled until a filter is
                  active (a bare link is just the page). */}
              <CopyDeliveryLinkButton filters={deliveryFilterState} />
            </div>
          )}
        </div>
        <WebhookDeliveryBreadcrumb
          filters={deliveryFilterState}
          onClear={clearDeliveryFilter}
          onClearAll={clearAllDeliveryFilters}
        />
        {/* Status legend swatch row (F101) -- success / failed / pending with
            LIVE counts so a glance reads the delivery health, and each swatch
            is a one-click status filter (clicking the active one clears it).
            Mirrors the felt-green / red / amber the status column already uses.
            Only shown once there are deliveries to summarise. */}
        {deliveries.length > 0 && (
          <div
            className="flex flex-wrap items-center gap-2 mb-2"
            role="radiogroup"
            aria-label="Filter deliveries by status"
            onKeyDown={onStatusRadioKeyDown}
          >
            {statusCounts.map(({ status, label, count }, i) => {
              const active = statusFilter === status;
              const color = STATUS_SWATCH[status] ?? "var(--color-ink)";
              const a11y = statusSwatchAria(label, count, active);
              // Roving tabindex: the selected swatch is the single tab stop;
              // with no status selected the first swatch is reachable (F128).
              const selectedIdx = statusCounts.findIndex(
                (s) => s.status === statusFilter,
              );
              const tabbable = radioTabbableIndex(selectedIdx, statusCounts.length);
              return (
                <button
                  key={status}
                  ref={(el) => {
                    statusRadioRefs.current[i] = el;
                  }}
                  type="button"
                  role="radio"
                  onClick={() => toggleStatusFilter(status)}
                  aria-checked={active}
                  tabIndex={i === tabbable ? 0 : -1}
                  aria-label={a11y.ariaLabel}
                  title={a11y.title}
                  className="inline-flex items-center gap-1.5 rounded-sm border px-2 py-[3px] text-[11px] transition-colors hover:bg-black/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-cue)] focus-visible:ring-offset-1"
                  style={{
                    borderColor: active ? color : "var(--color-rule)",
                    background: active ? `${color}14` : "transparent",
                  }}
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full shrink-0"
                    style={{ background: color }}
                    aria-hidden
                  />
                  <span className="opacity-80" aria-hidden>{label}</span>
                  <span className="num font-medium" style={{ color }} aria-hidden>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        )}
        {/* "Filtering N of M deliveries" line (F102) -- signals how much the
            active F92 filter hid, mirroring the shots filter-count pill (F91)
            and the notifications N-of-M line. Renders only when the view is
            actually narrowed (the helper returns null otherwise). */}
        {(() => {
          const label = deliveryFilterCountLabel(
            filteredDeliveries.length,
            deliveries.length,
          );
          return label ? (
            <p className="num text-[11px] opacity-60 mb-2" role="status">
              {label}
            </p>
          ) : null;
        })()}
        {deliveries.length === 0 ? (
          <p className="text-sm opacity-60">
            No deliveries yet. Send a test event or run a classification.
          </p>
        ) : filteredDeliveries.length === 0 ? (
          // Filtered-to-empty (F108): the canonical bare EmptyState instead of
          // a plain sentence, matching the /shots filtered empty state. The
          // copy names the active filter and the primary CTA clears it.
          <FilterEmptyState
            variant="bare"
            eyebrow="No matches"
            icon={<PaperPlaneTilt size={24} weight="duotone" />}
            title="No deliveries match that filter"
            body={deliveryEmptyBody}
            primary={{
              label: "Clear the filter",
              kind: "cue",
              onClick: clearAllDeliveryFilters,
            }}
            data-testid="webhook-deliveries-empty"
          />
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
                  {/* Per-row "Copy as ..." menu column (F123). Header is a
                      decorative glyph + a hover title; the real label lives on
                      each row button's aria-label. */}
                  <th className="px-3 py-2 w-9">
                    <span
                      className="inline-flex opacity-40"
                      title="Copy a delivery as JSON or Markdown"
                      aria-label="Copy"
                    >
                      <DotsThreeOutline size={13} weight="duotone" aria-hidden />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredDeliveries.map((d) => (
                  <tr
                    key={d.id}
                    className="border-t"
                    style={{ borderColor: "var(--color-rule)" }}
                  >
                    <td className="px-3 py-2 font-mono whitespace-nowrap">
                      <div>{fmtDate(d.created_at)}</div>
                      {/* Glanceable relative time (F129) so a burst of recent
                          attempts reads at a glance; absolute time stays as the
                          row's title. Empty for an unparseable timestamp. */}
                      {(() => {
                        const rel = deliveryRelativeLabel(d.created_at, nowMs);
                        return rel ? (
                          <div
                            className="text-[10px] opacity-50"
                            title={d.created_at ?? undefined}
                          >
                            {rel}
                          </div>
                        ) : null;
                      })()}
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
                      {/* Inline retry (F147): only failed rows offer it; the
                          button spins on its own id and toasts the outcome. */}
                      {canRetryDelivery(d) && (
                        <button
                          type="button"
                          onClick={() => onRetryDelivery(d)}
                          disabled={retrying !== null}
                          aria-label={retryAriaLabel(d.event)}
                          className="ml-2 inline-flex items-center gap-1 text-[11px] underline-offset-2 hover:underline disabled:opacity-50"
                          style={{ color: "var(--color-felt)" }}
                        >
                          {retrying === d.id && (
                            <CircleNotch size={11} weight="bold" className="animate-spin" />
                          )}
                          {retryButtonLabel(retrying === d.id)}
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <DeliveryExportMenu
                        delivery={d}
                        shortId={d.id.slice(0, 8)}
                      />
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
