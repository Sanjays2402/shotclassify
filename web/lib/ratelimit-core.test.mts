// Rate-limit core: workspace isolation, plan presets, per-key vs per-workspace
// bounds, header shape, and Retry-After semantics. Pure logic, no Next imports.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PLAN_DEFAULTS,
  _resetCountersForTest,
  checkAndConsume,
  defaultConfig,
  getConfigAt,
  setConfigAt,
  snapshot,
  readConfigStoreAt,
} from "./ratelimit-core.ts";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";

function tmpFile(): string {
  return path.join(os.tmpdir(), `rl-${process.pid}-${Math.random().toString(36).slice(2)}.json`);
}

test("plan defaults are sane and ascend", () => {
  assert.ok(PLAN_DEFAULTS.free.workspace_per_minute < PLAN_DEFAULTS.pro.workspace_per_minute);
  assert.ok(PLAN_DEFAULTS.pro.workspace_per_day < PLAN_DEFAULTS.team.workspace_per_day);
  for (const plan of ["free", "pro", "team"] as const) {
    const l = PLAN_DEFAULTS[plan];
    assert.ok(l.workspace_per_minute > 0);
    assert.ok(l.workspace_per_day > 0);
    assert.ok(l.key_per_minute > 0);
    assert.ok(l.key_per_day > 0);
  }
});

test("checkAndConsume allows under limit and blocks at limit", () => {
  _resetCountersForTest();
  const cfg = defaultConfig("ws-a");
  cfg.limits = { workspace_per_minute: 3, workspace_per_day: 1000, key_per_minute: 3, key_per_day: 1000 };
  const t0 = 1_700_000_000_000;
  for (let i = 0; i < 3; i++) {
    const d = checkAndConsume({ workspaceId: "ws-a", keyId: "k1", config: cfg, now: t0 });
    assert.equal(d.allowed, true, `request ${i + 1} should pass`);
    assert.equal(d.headers["X-RateLimit-Limit"], "3");
  }
  const blocked = checkAndConsume({ workspaceId: "ws-a", keyId: "k1", config: cfg, now: t0 });
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.bounded_by, "workspace_per_minute");
  assert.ok(Number(blocked.headers["Retry-After"]) > 0);
  assert.equal(blocked.headers["X-RateLimit-Remaining"], "0");
});

test("workspaces do not share counters (cross-tenant isolation)", () => {
  _resetCountersForTest();
  const cfg = defaultConfig("anything");
  cfg.limits = { workspace_per_minute: 2, workspace_per_day: 100, key_per_minute: 2, key_per_day: 100 };
  const t0 = 1_700_000_000_000;
  // Saturate workspace A. Each workspace owns its own keys, so use distinct
  // key ids that match the production invariant: an sk_live key is bound
  // to exactly one workspace.
  assert.equal(checkAndConsume({ workspaceId: "ws-a", keyId: "ws-a-k", config: cfg, now: t0 }).allowed, true);
  assert.equal(checkAndConsume({ workspaceId: "ws-a", keyId: "ws-a-k", config: cfg, now: t0 }).allowed, true);
  assert.equal(checkAndConsume({ workspaceId: "ws-a", keyId: "ws-a-k", config: cfg, now: t0 }).allowed, false);
  // Workspace B has its own bucket and is unaffected.
  const d1 = checkAndConsume({ workspaceId: "ws-b", keyId: "ws-b-k", config: cfg, now: t0 });
  const d2 = checkAndConsume({ workspaceId: "ws-b", keyId: "ws-b-k", config: cfg, now: t0 });
  assert.equal(d1.allowed, true);
  assert.equal(d2.allowed, true);
  const snapA = snapshot("ws-a", "ws-a-k", t0);
  const snapB = snapshot("ws-b", "ws-b-k", t0);
  assert.equal(snapA.workspace_per_minute_used, 2);
  assert.equal(snapB.workspace_per_minute_used, 2);
  // Each tenant sees its own counter only
});

test("per-key bound triggers even when workspace headroom remains", () => {
  _resetCountersForTest();
  const cfg = defaultConfig("ws-c");
  cfg.limits = { workspace_per_minute: 100, workspace_per_day: 100, key_per_minute: 1, key_per_day: 100 };
  const t0 = 1_700_000_000_000;
  assert.equal(checkAndConsume({ workspaceId: "ws-c", keyId: "k-tight", config: cfg, now: t0 }).allowed, true);
  const blocked = checkAndConsume({ workspaceId: "ws-c", keyId: "k-tight", config: cfg, now: t0 });
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.bounded_by, "key_per_minute");
  // A different key in the same workspace still has its own budget
  const other = checkAndConsume({ workspaceId: "ws-c", keyId: "k-other", config: cfg, now: t0 });
  assert.equal(other.allowed, true);
});

test("counter resets when the window rolls over", () => {
  _resetCountersForTest();
  const cfg = defaultConfig("ws-d");
  cfg.limits = { workspace_per_minute: 1, workspace_per_day: 1000, key_per_minute: 1, key_per_day: 1000 };
  const t0 = 1_700_000_000_000;
  assert.equal(checkAndConsume({ workspaceId: "ws-d", keyId: "k", config: cfg, now: t0 }).allowed, true);
  assert.equal(checkAndConsume({ workspaceId: "ws-d", keyId: "k", config: cfg, now: t0 + 100 }).allowed, false);
  // One full minute later the bucket is fresh.
  const after = checkAndConsume({ workspaceId: "ws-d", keyId: "k", config: cfg, now: t0 + 60_000 });
  assert.equal(after.allowed, true);
});

test("config store persists plan + limits per workspace", async () => {
  const p = tmpFile();
  try {
    await setConfigAt(p, "tenant-1", { plan: "pro" });
    await setConfigAt(p, "tenant-2", { plan: "team", limits: { key_per_minute: 17 } });
    const t1 = await getConfigAt(p, "tenant-1");
    const t2 = await getConfigAt(p, "tenant-2");
    assert.equal(t1.plan, "pro");
    assert.equal(t1.limits.key_per_minute, PLAN_DEFAULTS.pro.key_per_minute);
    assert.equal(t2.plan, "team");
    assert.equal(t2.limits.key_per_minute, 17);
    // Unknown tenant returns a default, not an error.
    const t3 = await getConfigAt(p, "never-seen");
    assert.equal(t3.plan, "free");
    // Store is a real file with both rows.
    const store = await readConfigStoreAt(p);
    assert.ok(store.workspaces["tenant-1"]);
    assert.ok(store.workspaces["tenant-2"]);
  } finally {
    await fs.unlink(p).catch(() => {});
  }
});

test("setConfigAt clamps negatives and floors floats", async () => {
  const p = tmpFile();
  try {
    const out = await setConfigAt(p, "ws", {
      plan: "custom",
      limits: { workspace_per_minute: -50, key_per_minute: 12.9 },
    });
    assert.equal(out.limits.workspace_per_minute, 0);
    assert.equal(out.limits.key_per_minute, 12);
  } finally {
    await fs.unlink(p).catch(() => {});
  }
});
