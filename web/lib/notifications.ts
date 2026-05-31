// File-backed in-app notification store.
//
// Notifications are produced as a side-effect of:
//   * a successful classification (via /api/classify or /v1/classify),
//   * a failed webhook delivery (after retries are exhausted),
//   * any code path that calls notify(...).
//
// They render in the header bell + on /notifications. Newest first.
// Mutations are written atomically to JSON; reads are tolerant of a missing file.
//
// No `server-only` import: this module is only ever imported by server route
// handlers and by lib/webhooks.ts, which is itself server-only. Keeping it
// framework-free lets the unit tests run under plain tsx.
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

import { isKindEnabled } from "./notification-prefs";

export type NotificationKind =
  | "classify.completed"
  | "webhook.failed"
  | "system";

export type Notification = {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  href: string | null;
  created_at: string;
  read_at: string | null;
};

const ROOT =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const NOTIFS_PATH = path.join(ROOT, "notifications.json");
const MAX = 200;

async function readAll(): Promise<Notification[]> {
  try {
    const raw = await fs.readFile(NOTIFS_PATH, "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err: any) {
    if (err?.code === "ENOENT") return [];
    return [];
  }
}

async function writeAll(items: Notification[]): Promise<void> {
  await fs.mkdir(path.dirname(NOTIFS_PATH), { recursive: true });
  const tmp = `${NOTIFS_PATH}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(items, null, 2), "utf8");
  await fs.rename(tmp, NOTIFS_PATH);
}

export async function listNotifications(limit = 100): Promise<Notification[]> {
  const all = await readAll();
  return all.slice(0, Math.min(Math.max(limit, 1), MAX));
}

export async function unreadCount(): Promise<number> {
  const all = await readAll();
  return all.reduce((acc, n) => acc + (n.read_at ? 0 : 1), 0);
}

export async function notify(input: {
  kind: NotificationKind;
  title: string;
  body: string;
  href?: string | null;
}): Promise<Notification | null> {
  // Honour per-deployment notification preferences. When a kind is muted
  // the call becomes a no-op so callers don't need to know about prefs.
  if (!(await isKindEnabled(input.kind))) return null;
  const title = (input.title || "").trim().slice(0, 140) || "Notification";
  const body = (input.body || "").trim().slice(0, 480);
  const item: Notification = {
    id: crypto.randomUUID(),
    kind: input.kind,
    title,
    body,
    href: input.href ?? null,
    created_at: new Date().toISOString(),
    read_at: null,
  };
  const all = await readAll();
  all.unshift(item);
  await writeAll(all.slice(0, MAX));
  return item;
}

export async function markRead(id: string): Promise<Notification | null> {
  const all = await readAll();
  const found = all.find((n) => n.id === id);
  if (!found) return null;
  if (!found.read_at) found.read_at = new Date().toISOString();
  await writeAll(all);
  return found;
}

export async function markAllRead(): Promise<number> {
  const all = await readAll();
  const now = new Date().toISOString();
  let n = 0;
  for (const item of all) {
    if (!item.read_at) {
      item.read_at = now;
      n += 1;
    }
  }
  if (n > 0) await writeAll(all);
  return n;
}

export async function clearAll(): Promise<number> {
  const all = await readAll();
  const n = all.length;
  if (n > 0) await writeAll([]);
  return n;
}

export async function deleteOne(id: string): Promise<boolean> {
  const all = await readAll();
  const next = all.filter((n) => n.id !== id);
  if (next.length === all.length) return false;
  await writeAll(next);
  return true;
}

// Convenience builders kept here so call sites stay tiny and consistent.
export async function notifyClassifyCompleted(result: any): Promise<void> {
  try {
    const id =
      (result && (result.shot_id || result.id)) ||
      (typeof result?.result?.id === "string" ? result.result.id : null);
    const cat =
      result?.primary_category ||
      result?.category ||
      result?.result?.primary_category ||
      "shot";
    const confRaw =
      result?.confidence ?? result?.result?.confidence ?? null;
    const conf =
      typeof confRaw === "number" ? `${Math.round(confRaw * 100)}%` : null;
    const title = `Classified as ${cat}`;
    const body = conf
      ? `Confidence ${conf}. Open the shot for details.`
      : "A new shot finished classifying.";
    const href = id ? `/shots/${id}` : "/shots";
    await notify({ kind: "classify.completed", title, body, href });
  } catch {
    /* never throw from notification builders */
  }
}

export async function notifyWebhookFailed(input: {
  url: string;
  http_status: number | null;
  error: string | null;
  attempts: number;
}): Promise<void> {
  try {
    const status = input.http_status ? `HTTP ${input.http_status}` : "no response";
    const detail = input.error ? `: ${input.error}` : "";
    await notify({
      kind: "webhook.failed",
      title: "Webhook delivery failed",
      body: `${input.url} returned ${status} after ${input.attempts} attempts${detail}`,
      href: "/webhooks",
    });
  } catch {
    /* swallow */
  }
}
