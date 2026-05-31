// Cross-tenant isolation for the webhook subsystem. Two workspaces must
// never observe each other's subscriptions, deliveries, or replays, and a
// dispatch for one tenant must not fan out to the other tenant's hooks.
import { test } from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { createRequire } from "node:module";

const nodeRequire = createRequire(import.meta.url);
const serverOnlyPath = nodeRequire.resolve("server-only");
nodeRequire.cache[serverOnlyPath] = {
  id: serverOnlyPath,
  filename: serverOnlyPath,
  loaded: true,
  exports: {},
  children: [],
  paths: [],
  // @ts-expect-error minimal Module shape
  require: nodeRequire,
};

const tmpDir = await fs.mkdtemp(
  path.join(os.tmpdir(), "shotclassify-tenant-"),
);
process.env.SHOTCLASSIFY_STORE_DIR = tmpDir;
// Loopback delivery targets are blocked by SSRF in prod. The dispatch test
// below uses a localhost echo, so flip the test escape hatch on.
process.env.SHOTCLASSIFY_WEBHOOK_ALLOW_LOOPBACK = "1";

const {
  createWebhook,
  listWebhooks,
  getWebhook,
  deleteWebhook,
  setActive,
  listDeliveries,
  listDeliveriesPage,
  redeliver,
  dispatchEvent,
  testFire,
} = await import("./webhooks");
const { readWebhookAllowlist, writeWebhookAllowlist } = await import(
  "./webhook-allowlist"
);

function startServer(
  handler: (req: http.IncomingMessage, res: http.ServerResponse) => void,
): Promise<{ url: string; close: () => Promise<void> }> {
  return new Promise((resolve) => {
    const srv = http.createServer(handler);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address() as AddressInfo;
      resolve({
        url: `http://127.0.0.1:${port}/hook`,
        close: () => new Promise((r) => srv.close(() => r())),
      });
    });
  });
}

test("acme cannot see globex webhooks", async () => {
  const a = await createWebhook({
    url: "https://example.com/acme",
    description: "acme hook",
    workspaceId: "acme",
  });
  const g = await createWebhook({
    url: "https://example.com/globex",
    description: "globex hook",
    workspaceId: "globex",
  });

  const acmeList = await listWebhooks("acme");
  const globexList = await listWebhooks("globex");

  assert.ok(acmeList.find((h) => h.id === a.id));
  assert.ok(!acmeList.find((h) => h.id === g.id), "acme leaked globex hook");
  assert.ok(globexList.find((h) => h.id === g.id));
  assert.ok(!globexList.find((h) => h.id === a.id), "globex leaked acme hook");
});

test("getWebhook + delete refuse cross-tenant access", async () => {
  const a = await createWebhook({
    url: "https://example.com/x",
    workspaceId: "acme",
  });

  // Globex tries to fetch acme's hook by id.
  const stolen = await getWebhook(a.id, "globex");
  assert.equal(stolen, null, "cross-tenant getWebhook must return null");

  // Globex tries to delete acme's hook by id.
  const deleted = await deleteWebhook(a.id, "globex");
  assert.equal(deleted, false, "cross-tenant deleteWebhook must refuse");

  // The hook still belongs to acme.
  const still = await getWebhook(a.id, "acme");
  assert.ok(still, "acme hook must survive a cross-tenant delete attempt");

  // Globex cannot disable acme's hook either.
  const toggled = await setActive(a.id, false, "globex");
  assert.equal(toggled, null, "cross-tenant setActive must refuse");
  const reread = await getWebhook(a.id, "acme");
  assert.equal(reread?.active, true, "acme hook active state was mutated");
});

test("dispatchEvent only fans out to the calling tenant", async () => {
  let acmeHits = 0;
  let globexHits = 0;
  const acmeSrv = await startServer((_req, res) => {
    acmeHits += 1;
    res.statusCode = 200;
    res.end("ok");
  });
  const globexSrv = await startServer((_req, res) => {
    globexHits += 1;
    res.statusCode = 200;
    res.end("ok");
  });

  await createWebhook({
    url: acmeSrv.url,
    events: ["classify.completed"],
    workspaceId: "acme",
  });
  await createWebhook({
    url: globexSrv.url,
    events: ["classify.completed"],
    workspaceId: "globex",
  });

  await dispatchEvent("acme", "classify.completed", { hello: "acme" });
  // dispatchEvent is fire-and-forget. Give the in-process deliveries a tick.
  await new Promise((r) => setTimeout(r, 250));

  assert.equal(acmeHits, 1, "acme hook should have been called once");
  assert.equal(globexHits, 0, "globex hook must not receive acme events");

  await acmeSrv.close();
  await globexSrv.close();
});

test("deliveries and redeliver are scoped to the owning tenant", async () => {
  const srv = await startServer((_req, res) => {
    res.statusCode = 200;
    res.end("ok");
  });
  const hook = await createWebhook({
    url: srv.url,
    workspaceId: "acme",
    events: ["ping"],
  });
  const delivery = await testFire(hook);

  const acmePage = await listDeliveriesPage(hook.id, "acme", {});
  assert.ok(
    acmePage.deliveries.find((d) => d.id === delivery.id),
    "acme should see its own delivery",
  );

  const globexPage = await listDeliveriesPage(hook.id, "globex", {});
  assert.equal(
    globexPage.deliveries.length,
    0,
    "globex must not see acme deliveries even with the webhook id",
  );
  const globexAll = await listDeliveries(undefined, "globex");
  assert.ok(
    !globexAll.find((d) => d.id === delivery.id),
    "globex must not see acme delivery in unfiltered list",
  );

  // Replay attempt by globex must be rejected as not_found.
  const replay = await redeliver(delivery.id, "globex");
  assert.deepEqual(replay, { error: "delivery_not_found" });

  await srv.close();
});

test("allowlist is partitioned per workspace", async () => {
  await writeWebhookAllowlist(["acme.internal"], "acme");
  await writeWebhookAllowlist(["globex.internal"], "globex");

  const acme = await readWebhookAllowlist("acme");
  const globex = await readWebhookAllowlist("globex");

  assert.deepEqual(acme, ["acme.internal"]);
  assert.deepEqual(globex, ["globex.internal"]);
  assert.ok(!acme.includes("globex.internal"));
  assert.ok(!globex.includes("acme.internal"));
});
