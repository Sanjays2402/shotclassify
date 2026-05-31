// File-backed webhook subscription + delivery log store.
// Subscriptions fire on successful /v1/classify (and /api/classify proxy) calls.
// Each delivery is recorded with status, response code, latency, and attempt count.
// A signing secret is generated per subscription; deliveries are signed with
// X-Shotclassify-Signature: sha256=<hmac> over the raw JSON body.
import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { notifyWebhookFailed } from "./notifications";
import { checkOutboundUrl } from "./url-safety";
import { readWebhookAllowlist } from "./webhook-allowlist";
import { DEFAULT_WORKSPACE_ID, normalizeWorkspaceId } from "./keystore-core";

export type Webhook = {
  id: string;
  workspace_id: string;
  url: string;
  description: string;
  secret: string; // shown to user; used for HMAC
  events: string[]; // e.g. ["classify.completed"]
  active: boolean;
  created_at: string;
  last_delivery_at: string | null;
  success_count: number;
  failure_count: number;
};

export type Delivery = {
  id: string;
  workspace_id: string;
  webhook_id: string;
  event: string;
  url: string;
  status: "success" | "failed" | "pending";
  attempt: number;
  http_status: number | null;
  error: string | null;
  latency_ms: number | null;
  created_at: string;
  payload_preview: string; // first 240 chars
};

const ROOT =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const HOOKS_PATH = path.join(ROOT, "webhooks.json");
const DELIVERIES_PATH = path.join(ROOT, "webhook_deliveries.json");
const MAX_DELIVERIES = 200;
const MAX_ATTEMPTS = 4;
const RETRY_BACKOFF_MS = [2_000, 10_000, 30_000];

async function readJson<T>(p: string, fallback: T): Promise<T> {
  try {
    const raw = await fs.readFile(p, "utf8");
    return JSON.parse(raw) as T;
  } catch (err: any) {
    if (err?.code === "ENOENT") return fallback;
    throw err;
  }
}

// Backfill workspace_id for legacy rows written before multi-tenancy. Keeps
// older installs working without a manual migration step.
function migrateHook(h: Webhook): Webhook {
  if (!h.workspace_id) return { ...h, workspace_id: DEFAULT_WORKSPACE_ID };
  return h;
}
function migrateDelivery(d: Delivery): Delivery {
  if (!d.workspace_id) return { ...d, workspace_id: DEFAULT_WORKSPACE_ID };
  return d;
}
async function readHooks(): Promise<Webhook[]> {
  const raw = await readJson<Webhook[]>(HOOKS_PATH, []);
  return raw.map(migrateHook);
}
async function readDeliveries(): Promise<Delivery[]> {
  const raw = await readJson<Delivery[]>(DELIVERIES_PATH, []);
  return raw.map(migrateDelivery);
}

async function writeJson(p: string, data: unknown): Promise<void> {
  await fs.mkdir(path.dirname(p), { recursive: true });
  const tmp = `${p}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(data, null, 2), "utf8");
  await fs.rename(tmp, p);
}

export async function listWebhooks(workspaceId: string): Promise<Webhook[]> {
  const ws = normalizeWorkspaceId(workspaceId);
  const all = await readHooks();
  return all
    .filter((h) => h.workspace_id === ws)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export async function getWebhook(
  id: string,
  workspaceId: string,
): Promise<Webhook | null> {
  const ws = normalizeWorkspaceId(workspaceId);
  const all = await readHooks();
  return all.find((h) => h.id === id && h.workspace_id === ws) || null;
}

export async function createWebhook(input: {
  url: string;
  description?: string;
  events?: string[];
  workspaceId: string;
}): Promise<Webhook> {
  const ws = normalizeWorkspaceId(input.workspaceId);
  const url = (input.url || "").trim();
  if (!/^https?:\/\//i.test(url)) {
    throw new Error("URL must start with http:// or https://");
  }
  try {
    new URL(url);
  } catch {
    throw new Error("Invalid URL");
  }
  // Pre-flight SSRF check. We do a DNS-aware check here so the user gets
  // immediate feedback at save time, then re-check at every delivery in
  // case DNS rebinds to a private address after creation.
  const allow = await readWebhookAllowlist(ws);
  const safety = await checkOutboundUrl(url, { allowHostnames: allow });
  if (!safety.ok) {
    throw new Error(`Webhook URL rejected: ${safety.message}`);
  }
  const hook: Webhook = {
    id: crypto.randomUUID(),
    workspace_id: ws,
    url,
    description: (input.description || "").slice(0, 200),
    secret: `whsec_${crypto.randomBytes(24).toString("base64url")}`,
    events: (input.events && input.events.length
      ? input.events
      : ["classify.completed"]
    ).slice(0, 8),
    active: true,
    created_at: new Date().toISOString(),
    last_delivery_at: null,
    success_count: 0,
    failure_count: 0,
  };
  const all = await readHooks();
  all.push(hook);
  await writeJson(HOOKS_PATH, all);
  return hook;
}

export async function deleteWebhook(
  id: string,
  workspaceId: string,
): Promise<boolean> {
  const ws = normalizeWorkspaceId(workspaceId);
  const all = await readHooks();
  const target = all.find((h) => h.id === id);
  if (!target || target.workspace_id !== ws) return false;
  const next = all.filter((h) => h.id !== id);
  await writeJson(HOOKS_PATH, next);
  return true;
}

export async function setActive(
  id: string,
  active: boolean,
  workspaceId: string,
): Promise<Webhook | null> {
  const ws = normalizeWorkspaceId(workspaceId);
  const all = await readHooks();
  const h = all.find((x) => x.id === id);
  if (!h || h.workspace_id !== ws) return null;
  h.active = active;
  await writeJson(HOOKS_PATH, all);
  return h;
}

async function recordDelivery(d: Delivery): Promise<void> {
  const all = await readDeliveries();
  all.unshift(d);
  const trimmed = all.slice(0, MAX_DELIVERIES);
  await writeJson(DELIVERIES_PATH, trimmed);
}

async function bumpCounters(
  id: string,
  success: boolean,
  at: string,
): Promise<void> {
  const all = await readHooks();
  const h = all.find((x) => x.id === id);
  if (!h) return;
  h.last_delivery_at = at;
  if (success) h.success_count += 1;
  else h.failure_count += 1;
  await writeJson(HOOKS_PATH, all);
}

export type DeliveryFilter = {
  status?: "success" | "failed" | "pending";
  event?: string;
  offset?: number;
  limit?: number;
};

export type DeliveryPage = {
  deliveries: Delivery[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
};

export async function listDeliveries(
  webhookId: string | undefined,
  workspaceId: string,
  limitOrFilter: number | DeliveryFilter = 50,
): Promise<Delivery[]> {
  const filter: DeliveryFilter =
    typeof limitOrFilter === "number" ? { limit: limitOrFilter } : limitOrFilter;
  const page = await listDeliveriesPage(webhookId, workspaceId, filter);
  return page.deliveries;
}

export async function listDeliveriesPage(
  webhookId: string | undefined,
  workspaceId: string,
  filter: DeliveryFilter = {},
): Promise<DeliveryPage> {
  const ws = normalizeWorkspaceId(workspaceId);
  const all = await readDeliveries();
  let filtered = all.filter((d) => d.workspace_id === ws);
  if (webhookId) filtered = filtered.filter((d) => d.webhook_id === webhookId);
  if (filter.status) {
    filtered = filtered.filter((d) => d.status === filter.status);
  }
  if (filter.event) {
    filtered = filtered.filter((d) => d.event === filter.event);
  }
  const total = filtered.length;
  const offset = Math.max(0, Math.floor(filter.offset ?? 0));
  const rawLimit = Math.floor(filter.limit ?? 50);
  const limit = Math.max(1, Math.min(rawLimit, MAX_DELIVERIES));
  const slice = filtered.slice(offset, offset + limit);
  return {
    deliveries: slice,
    total,
    offset,
    limit,
    has_more: offset + slice.length < total,
  };
}

export async function listDeliveryEvents(
  webhookId: string | undefined,
  workspaceId: string,
): Promise<string[]> {
  const ws = normalizeWorkspaceId(workspaceId);
  const all = await readDeliveries();
  let filtered = all.filter((d) => d.workspace_id === ws);
  if (webhookId) filtered = filtered.filter((d) => d.webhook_id === webhookId);
  return Array.from(new Set(filtered.map((d) => d.event))).sort();
}

export function sign(secret: string, body: string): string {
  return (
    "sha256=" +
    crypto.createHmac("sha256", secret).update(body).digest("hex")
  );
}

async function attemptDelivery(
  hook: Webhook,
  body: string,
  signature: string,
  event: string,
  attempt: number,
): Promise<{ ok: boolean; status: number | null; error: string | null; latency: number }> {
  const t0 = Date.now();
  // Re-validate the URL at delivery time. Defends against DNS rebinding and
  // against allowlist edits made after the subscription was created.
  try {
    const allow = await readWebhookAllowlist(hook.workspace_id);
    const safety = await checkOutboundUrl(hook.url, { allowHostnames: allow });
    if (!safety.ok) {
      return {
        ok: false,
        status: null,
        error: `ssrf_blocked: ${safety.reason}`,
        latency: Date.now() - t0,
      };
    }
  } catch (err: any) {
    return {
      ok: false,
      status: null,
      error: `safety_check_failed: ${err?.message || "unknown"}`,
      latency: Date.now() - t0,
    };
  }
  try {
    const ac = new AbortController();
    const timeout = setTimeout(() => ac.abort(), 8_000);
    const res = await fetch(hook.url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "user-agent": "shotclassify-webhook/1",
        "x-shotclassify-event": event,
        "x-shotclassify-delivery-attempt": String(attempt),
        "x-shotclassify-signature": signature,
      },
      body,
      signal: ac.signal,
    });
    clearTimeout(timeout);
    const latency = Date.now() - t0;
    const ok = res.status >= 200 && res.status < 300;
    return { ok, status: res.status, error: ok ? null : `HTTP ${res.status}`, latency };
  } catch (err: any) {
    return {
      ok: false,
      status: null,
      error: err?.name === "AbortError" ? "timeout after 8s" : err?.message || "delivery failed",
      latency: Date.now() - t0,
    };
  }
}

async function deliverWithRetries(
  hook: Webhook,
  event: string,
  payload: unknown,
): Promise<void> {
  const body = JSON.stringify(payload);
  const signature = sign(hook.secret, body);
  const preview = body.slice(0, 240);
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const r = await attemptDelivery(hook, body, signature, event, attempt);
    const now = new Date().toISOString();
    const delivery: Delivery = {
      id: crypto.randomUUID(),
      workspace_id: hook.workspace_id,
      webhook_id: hook.id,
      event,
      url: hook.url,
      status: r.ok ? "success" : "failed",
      attempt,
      http_status: r.status,
      error: r.error,
      latency_ms: r.latency,
      created_at: now,
      payload_preview: preview,
    };
    await recordDelivery(delivery);
    await bumpCounters(hook.id, r.ok, now);
    if (r.ok) return;
    if (attempt === MAX_ATTEMPTS) {
      notifyWebhookFailed({
        url: hook.url,
        http_status: r.status,
        error: r.error,
        attempts: attempt,
      }).catch(() => {});
      return;
    }
    const wait = RETRY_BACKOFF_MS[attempt - 1] ?? 30_000;
    await new Promise((res) => setTimeout(res, wait));
  }
}

// Fire-and-forget dispatch to all active webhooks subscribed to event for a
// single workspace. Cross-tenant fan-out is impossible by construction: a
// caller must pass the workspace_id of the API key that triggered the event.
export async function dispatchEvent(
  workspaceId: string,
  event: string,
  payload: unknown,
): Promise<void> {
  const ws = normalizeWorkspaceId(workspaceId);
  let hooks: Webhook[] = [];
  try {
    hooks = await listWebhooks(ws);
  } catch {
    return;
  }
  const targets = hooks.filter((h) => h.active && h.events.includes(event));
  if (targets.length === 0) return;
  for (const h of targets) {
    deliverWithRetries(h, event, payload).catch(() => {});
  }
}

// Replay a recorded delivery against its current webhook target.
// Returns the new Delivery, or null if either the delivery or its webhook
// no longer exists. Single attempt, awaited so the UI can show the result.
// A workspace mismatch returns delivery_not_found so a tenant can never even
// learn the id space of another tenant's deliveries.
export async function redeliver(
  deliveryId: string,
  workspaceId: string,
): Promise<{ delivery: Delivery } | { error: "delivery_not_found" | "webhook_not_found" }> {
  const ws = normalizeWorkspaceId(workspaceId);
  const all = await readDeliveries();
  const prior = all.find((d) => d.id === deliveryId && d.workspace_id === ws);
  if (!prior) return { error: "delivery_not_found" };
  const hook = await getWebhook(prior.webhook_id, ws);
  if (!hook) return { error: "webhook_not_found" };
  // Reconstruct the body we can replay. We only stored a preview, so we send
  // a replay envelope that references the original delivery for traceability.
  const payload = {
    event: prior.event,
    replay_of: prior.id,
    original_at: prior.created_at,
    original_payload_preview: prior.payload_preview,
    delivered_at: new Date().toISOString(),
  };
  const body = JSON.stringify(payload);
  const sig = sign(hook.secret, body);
  const r = await attemptDelivery(hook, body, sig, prior.event, 1);
  const now = new Date().toISOString();
  const delivery: Delivery = {
    id: crypto.randomUUID(),
    workspace_id: hook.workspace_id,
    webhook_id: hook.id,
    event: prior.event,
    url: hook.url,
    status: r.ok ? "success" : "failed",
    attempt: 1,
    http_status: r.status,
    error: r.error,
    latency_ms: r.latency,
    created_at: now,
    payload_preview: body.slice(0, 240),
  };
  await recordDelivery(delivery);
  await bumpCounters(hook.id, r.ok, now);
  return { delivery };
}

// Synchronous test ping (single attempt, awaited so the UI can show the result).
export async function testFire(
  hook: Webhook,
): Promise<Delivery> {
  const payload = {
    event: "ping",
    delivered_at: new Date().toISOString(),
    webhook_id: hook.id,
    message: "This is a test delivery from ShotClassify.",
  };
  const body = JSON.stringify(payload);
  const sig = sign(hook.secret, body);
  const r = await attemptDelivery(hook, body, sig, "ping", 1);
  const now = new Date().toISOString();
  const delivery: Delivery = {
    id: crypto.randomUUID(),
    workspace_id: hook.workspace_id,
    webhook_id: hook.id,
    event: "ping",
    url: hook.url,
    status: r.ok ? "success" : "failed",
    attempt: 1,
    http_status: r.status,
    error: r.error,
    latency_ms: r.latency,
    created_at: now,
    payload_preview: body.slice(0, 240),
  };
  await recordDelivery(delivery);
  await bumpCounters(hook.id, r.ok, now);
  return delivery;
}
