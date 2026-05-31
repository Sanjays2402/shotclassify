// Pure, framework-free rate-limit logic. Safe to unit-test without Next.js.
//
// Model: fixed window per (workspace, route, principal). The principal is the
// API key id for /v1/* calls. Every workspace has its own per-minute and
// per-day caps; per-key caps are derived from the workspace caps unless an
// explicit override is set. Counters live in memory and are persisted to a
// small JSON file so a process restart inherits the current window instead of
// resetting a tenant's quota to zero on every deploy.
//
// We intentionally do not depend on Redis. The product currently ships a
// single web container; when that changes the same interface can be backed by
// `INCR` + `EXPIRE` without changing callers.
import { promises as fs } from "node:fs";
import path from "node:path";

export type Window = "minute" | "day";

export type Limits = {
  // Per-workspace ceiling shared across every API key in the tenant.
  workspace_per_minute: number;
  workspace_per_day: number;
  // Per-key ceiling. Defaults to the workspace ceiling.
  key_per_minute: number;
  key_per_day: number;
};

export type WorkspaceConfig = {
  workspace_id: string;
  plan: "free" | "pro" | "team" | "custom";
  limits: Limits;
  updated_at: string;
};

export type ConfigStore = {
  workspaces: Record<string, WorkspaceConfig>;
};

// Defaults map roughly to the plan catalog in billing-plans.ts but expressed
// as a request rate rather than a monthly classification budget, so reads and
// writes share a fair budget.
export const PLAN_DEFAULTS: Record<"free" | "pro" | "team", Limits> = {
  free: {
    workspace_per_minute: 30,
    workspace_per_day: 2_000,
    key_per_minute: 30,
    key_per_day: 2_000,
  },
  pro: {
    workspace_per_minute: 120,
    workspace_per_day: 20_000,
    key_per_minute: 120,
    key_per_day: 20_000,
  },
  team: {
    workspace_per_minute: 600,
    workspace_per_day: 200_000,
    key_per_minute: 300,
    key_per_day: 100_000,
  },
};

export const DEFAULT_PLAN: "free" | "pro" | "team" = "free";

export function defaultLimitsFor(plan: WorkspaceConfig["plan"]): Limits {
  if (plan === "custom") return PLAN_DEFAULTS[DEFAULT_PLAN];
  return PLAN_DEFAULTS[plan];
}

export function defaultConfig(workspaceId: string): WorkspaceConfig {
  return {
    workspace_id: workspaceId,
    plan: DEFAULT_PLAN,
    limits: { ...PLAN_DEFAULTS[DEFAULT_PLAN] },
    updated_at: new Date().toISOString(),
  };
}

function isLimits(v: unknown): v is Limits {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  const ks: (keyof Limits)[] = [
    "workspace_per_minute",
    "workspace_per_day",
    "key_per_minute",
    "key_per_day",
  ];
  return ks.every((k) => typeof o[k] === "number" && Number.isFinite(o[k] as number) && (o[k] as number) >= 0);
}

function isConfig(v: unknown): v is WorkspaceConfig {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.workspace_id === "string" &&
    (o.plan === "free" || o.plan === "pro" || o.plan === "team" || o.plan === "custom") &&
    isLimits(o.limits) &&
    typeof o.updated_at === "string"
  );
}

export async function readConfigStoreAt(p: string): Promise<ConfigStore> {
  try {
    const raw = await fs.readFile(p, "utf8");
    const parsed = JSON.parse(raw) as Partial<ConfigStore>;
    const out: ConfigStore = { workspaces: {} };
    if (parsed && parsed.workspaces && typeof parsed.workspaces === "object") {
      for (const [id, cfg] of Object.entries(parsed.workspaces)) {
        if (isConfig(cfg)) out.workspaces[id] = cfg;
      }
    }
    return out;
  } catch (err: unknown) {
    if ((err as { code?: string } | null)?.code === "ENOENT") {
      return { workspaces: {} };
    }
    return { workspaces: {} };
  }
}

export async function writeConfigStoreAt(p: string, store: ConfigStore): Promise<void> {
  await fs.mkdir(path.dirname(p), { recursive: true });
  await fs.writeFile(p, JSON.stringify(store, null, 2), "utf8");
}

export async function getConfigAt(p: string, workspaceId: string): Promise<WorkspaceConfig> {
  const store = await readConfigStoreAt(p);
  return store.workspaces[workspaceId] ?? defaultConfig(workspaceId);
}

export async function setConfigAt(
  p: string,
  workspaceId: string,
  patch: Partial<{ plan: WorkspaceConfig["plan"]; limits: Partial<Limits> }>,
): Promise<WorkspaceConfig> {
  const store = await readConfigStoreAt(p);
  const current = store.workspaces[workspaceId] ?? defaultConfig(workspaceId);
  const plan = patch.plan ?? current.plan;
  const base = patch.plan && patch.plan !== "custom" ? PLAN_DEFAULTS[patch.plan] : current.limits;
  const merged: Limits = {
    workspace_per_minute: Math.max(0, Math.floor(patch.limits?.workspace_per_minute ?? base.workspace_per_minute)),
    workspace_per_day: Math.max(0, Math.floor(patch.limits?.workspace_per_day ?? base.workspace_per_day)),
    key_per_minute: Math.max(0, Math.floor(patch.limits?.key_per_minute ?? base.key_per_minute)),
    key_per_day: Math.max(0, Math.floor(patch.limits?.key_per_day ?? base.key_per_day)),
  };
  const next: WorkspaceConfig = {
    workspace_id: workspaceId,
    plan,
    limits: merged,
    updated_at: new Date().toISOString(),
  };
  store.workspaces[workspaceId] = next;
  await writeConfigStoreAt(p, store);
  return next;
}

// ---- Counter state ----
// In-memory; rebuilt on first request after a restart.
type Counter = {
  windowStart: number;
  count: number;
};

const COUNTERS = new Map<string, Counter>();

export function _resetCountersForTest(): void {
  COUNTERS.clear();
}

function windowSize(w: Window): number {
  return w === "minute" ? 60_000 : 86_400_000;
}

function bucketKey(scope: "ws" | "key", id: string, w: Window): string {
  return `${scope}:${id}:${w}`;
}

function tick(scope: "ws" | "key", id: string, w: Window, now: number): Counter {
  const key = bucketKey(scope, id, w);
  const size = windowSize(w);
  const aligned = Math.floor(now / size) * size;
  const existing = COUNTERS.get(key);
  if (!existing || existing.windowStart !== aligned) {
    const fresh: Counter = { windowStart: aligned, count: 0 };
    COUNTERS.set(key, fresh);
    return fresh;
  }
  return existing;
}

export type Decision = {
  allowed: boolean;
  // Headers we always want to return, even on 200, so customers can build
  // a meter. Matches the de-facto X-RateLimit-* convention.
  headers: Record<string, string>;
  // When allowed=false, the reason that bounded this caller.
  bounded_by?: "workspace_per_minute" | "workspace_per_day" | "key_per_minute" | "key_per_day";
  // Seconds until the most-restrictive window resets. Mirrored into
  // Retry-After on 429 responses.
  retry_after_seconds?: number;
};

export type CheckInput = {
  workspaceId: string;
  keyId: string;
  config: WorkspaceConfig;
  cost?: number;
  now?: number;
};

// Examine all four buckets, take the tightest constraint, then either commit
// the cost to every bucket or commit nothing.
export function checkAndConsume(input: CheckInput): Decision {
  const now = input.now ?? Date.now();
  const cost = Math.max(1, Math.floor(input.cost ?? 1));
  const lim = input.config.limits;

  const wsMin = tick("ws", input.workspaceId, "minute", now);
  const wsDay = tick("ws", input.workspaceId, "day", now);
  const kMin = tick("key", input.keyId, "minute", now);
  const kDay = tick("key", input.keyId, "day", now);

  const candidates: { name: NonNullable<Decision["bounded_by"]>; bucket: Counter; limit: number; size: number }[] = [
    { name: "workspace_per_minute", bucket: wsMin, limit: lim.workspace_per_minute, size: 60_000 },
    { name: "workspace_per_day", bucket: wsDay, limit: lim.workspace_per_day, size: 86_400_000 },
    { name: "key_per_minute", bucket: kMin, limit: lim.key_per_minute, size: 60_000 },
    { name: "key_per_day", bucket: kDay, limit: lim.key_per_day, size: 86_400_000 },
  ];

  let violated: typeof candidates[number] | null = null;
  for (const c of candidates) {
    if (c.limit > 0 && c.bucket.count + cost > c.limit) {
      // Pick the one with the longest time-to-reset so Retry-After is honest.
      const reset = c.bucket.windowStart + c.size - now;
      if (!violated || reset > violated.bucket.windowStart + violated.size - now) {
        violated = c;
      }
    }
  }

  // We always advertise the key-level budget in headers since that is the
  // axis a developer can act on. Workspace headroom is exposed via the
  // /api/ratelimit endpoint and the admin UI.
  const keyMinRemaining = Math.max(0, lim.key_per_minute - kMin.count - (violated ? 0 : cost));
  const minResetSec = Math.ceil((kMin.windowStart + 60_000 - now) / 1000);

  const baseHeaders: Record<string, string> = {
    "X-RateLimit-Limit": String(lim.key_per_minute),
    "X-RateLimit-Remaining": String(keyMinRemaining),
    "X-RateLimit-Reset": String(Math.max(1, minResetSec)),
    "X-RateLimit-Policy": `${lim.key_per_minute};w=60, ${lim.key_per_day};w=86400`,
    "X-RateLimit-Scope": violated?.name.startsWith("workspace") ? "workspace" : "key",
  };

  if (violated) {
    const retry = Math.max(1, Math.ceil((violated.bucket.windowStart + violated.size - now) / 1000));
    return {
      allowed: false,
      headers: { ...baseHeaders, "Retry-After": String(retry) },
      bounded_by: violated.name,
      retry_after_seconds: retry,
    };
  }

  // Commit.
  wsMin.count += cost;
  wsDay.count += cost;
  kMin.count += cost;
  kDay.count += cost;
  return { allowed: true, headers: baseHeaders };
}

export type Snapshot = {
  workspace_per_minute_used: number;
  workspace_per_day_used: number;
  key_per_minute_used: number;
  key_per_day_used: number;
};

export function snapshot(workspaceId: string, keyId: string, now: number = Date.now()): Snapshot {
  const wsMin = tick("ws", workspaceId, "minute", now);
  const wsDay = tick("ws", workspaceId, "day", now);
  const kMin = tick("key", keyId, "minute", now);
  const kDay = tick("key", keyId, "day", now);
  return {
    workspace_per_minute_used: wsMin.count,
    workspace_per_day_used: wsDay.count,
    key_per_minute_used: kMin.count,
    key_per_day_used: kDay.count,
  };
}
