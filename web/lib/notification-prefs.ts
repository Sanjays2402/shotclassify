// Per-deployment notification preferences.
//
// Controls which notification kinds get persisted by notify(). When a kind
// is muted, the corresponding call to notify() becomes a no-op for that
// kind, so users stop seeing them in the bell and on /notifications.
//
// Storage: a tiny JSON file next to notifications.json. No DB migration
// needed and the file is created lazily on first write. Defaults: all
// kinds enabled, matching prior behaviour.
import { promises as fs } from "node:fs";
import path from "node:path";

import type { NotificationKind } from "./notifications";

export type NotificationPrefs = {
  enabled: Record<NotificationKind, boolean>;
  updated_at: string | null;
};

const ROOT =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const PREFS_PATH = path.join(ROOT, "notification_prefs.json");

const ALL_KINDS: NotificationKind[] = [
  "classify.completed",
  "webhook.failed",
  "system",
];

export function defaultPrefs(): NotificationPrefs {
  return {
    enabled: {
      "classify.completed": true,
      "webhook.failed": true,
      system: true,
    },
    updated_at: null,
  };
}

export async function readPrefs(): Promise<NotificationPrefs> {
  try {
    const raw = await fs.readFile(PREFS_PATH, "utf8");
    const parsed = JSON.parse(raw) as Partial<NotificationPrefs>;
    const base = defaultPrefs();
    const enabled = { ...base.enabled };
    if (parsed && typeof parsed.enabled === "object" && parsed.enabled) {
      for (const k of ALL_KINDS) {
        const v = (parsed.enabled as Record<string, unknown>)[k];
        if (typeof v === "boolean") enabled[k] = v;
      }
    }
    return {
      enabled,
      updated_at:
        typeof parsed?.updated_at === "string" ? parsed.updated_at : null,
    };
  } catch (err: unknown) {
    const code = (err as { code?: string } | null)?.code;
    if (code === "ENOENT") return defaultPrefs();
    return defaultPrefs();
  }
}

export async function writePrefs(
  input: Partial<Record<NotificationKind, boolean>>,
): Promise<NotificationPrefs> {
  const current = await readPrefs();
  const next: NotificationPrefs = {
    enabled: { ...current.enabled },
    updated_at: new Date().toISOString(),
  };
  for (const k of ALL_KINDS) {
    const v = input[k];
    if (typeof v === "boolean") next.enabled[k] = v;
  }
  await fs.mkdir(path.dirname(PREFS_PATH), { recursive: true });
  const tmp = `${PREFS_PATH}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(next, null, 2), "utf8");
  await fs.rename(tmp, PREFS_PATH);
  return next;
}

export async function isKindEnabled(kind: NotificationKind): Promise<boolean> {
  const prefs = await readPrefs();
  // Unknown kinds fall through to enabled so future kinds aren't silently
  // dropped before someone adds a UI toggle for them.
  return prefs.enabled[kind] ?? true;
}

export const KIND_LABELS: Record<NotificationKind, { title: string; body: string }> = {
  "classify.completed": {
    title: "Classification complete",
    body: "A shot finishes classifying and a result lands in your history.",
  },
  "webhook.failed": {
    title: "Webhook delivery failed",
    body: "A webhook endpoint stops accepting deliveries after retries.",
  },
  system: {
    title: "System messages",
    body: "Operational notices from the platform itself.",
  },
};

export const ALL_NOTIFICATION_KINDS = ALL_KINDS;
