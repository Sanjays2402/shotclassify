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

export type Webhook = {
  id: string;
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

async function writeJson(p: string, data: unknown): Promise<void> {
  await fs.mkdir(path.dirname(p), { recursive: true });
  const tmp = `${p}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(data, null, 2), "utf8");
  await fs.rename(tmp, p);
}

export async function listWebhooks(): Promise<Webhook[]> {
  const all = await readJson<Webhook[]>(HOOKS_PATH, []);
  return all.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export async function getWebhook(id: string): Promise<Webhook | null> {
  const all = await readJson<Webhook[]>(HOOKS_PATH, []);
  return all.find((h) => h.id === id) || null;
}

export async function createWebhook(input: {
  url: string;
  description?: string;
  events?: string[];
}): Promise<Webhook> {
  const url = (input.url || "").trim();
  if (!/^https?:\/\//i.test(url)) {
    throw new Error("URL must start with http:// or https://");
  }
  try {
    new URL(url);
  } catch {
    throw new Error("Invalid URL");
  }
  const hook: Webhook = {
    id: crypto.randomUUID(),
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
  const all = await readJson<Webhook[]>(HOOKS_PATH, []);
  all.push(hook);
  await writeJson(HOOKS_PATH, all);
  return hook;
}

export async function deleteWebhook(id: string): Promise<boolean> {
  const all = await readJson<Webhook[]>(HOOKS_PATH, []);
  const next = all.filter((h) => h.id !== id);
  if (next.length === all.length) return false;
  await writeJson(HOOKS_PATH, next);
  return true;
}

export async function setActive(
  id: string,
  active: boolean,
): Promise<Webhook | null> {
  const all = await readJson<Webhook[]>(HOOKS_PATH, []);
  const h = all.find((x) => x.id === id);
  if (!h) return null;
  h.active = active;
  await writeJson(HOOKS_PATH, all);
  return h;
}

async function recordDelivery(d: Delivery): Promise<void> {
  const all = await readJson<Delivery[]>(DELIVERIES_PATH, []);
  all.unshift(d);
  // keep newest MAX_DELIVERIES
  const trimmed = all.slice(0, MAX_DELIVERIES);
  await writeJson(DELIVERIES_PATH, trimmed);
}

async function bumpCounters(
  id: string,
  success: boolean,
  at: string,
): Promise<void> {
  const all = await readJson<Webhook[]>(HOOKS_PATH, []);
  const h = all.find((x) => x.id === id);
  if (!h) return;
  h.last_delivery_at = at;
  if (success) h.success_count += 1;
  else h.failure_count += 1;
  await writeJson(HOOKS_PATH, all);
}

export async function listDeliveries(
  webhookId?: string,
  limit = 50,
): Promise<Delivery[]> {
  const all = await readJson<Delivery[]>(DELIVERIES_PATH, []);
  const filtered = webhookId
    ? all.filter((d) => d.webhook_id === webhookId)
    : all;
  return filtered.slice(0, Math.min(limit, MAX_DELIVERIES));
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

// Fire-and-forget dispatch to all active webhooks subscribed to event.
// Errors are logged into the delivery store, never thrown to the caller.
export async function dispatchEvent(
  event: string,
  payload: unknown,
): Promise<void> {
  let hooks: Webhook[] = [];
  try {
    hooks = await listWebhooks();
  } catch {
    return;
  }
  const targets = hooks.filter((h) => h.active && h.events.includes(event));
  if (targets.length === 0) return;
  // Wrap each in its own retry promise; do not await (caller already returned).
  for (const h of targets) {
    deliverWithRetries(h, event, payload).catch(() => {});
  }
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
