import { test } from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import http from "node:http";
import { createRequire } from "node:module";
import type { AddressInfo } from "node:net";

// Neutralize the `server-only` guard before importing webhooks.ts. The real
// package throws on import outside a React Server Component. We are exercising
// the pure file-store logic from a node:test runner.
const nodeRequire = createRequire(import.meta.url);
const serverOnlyPath = nodeRequire.resolve("server-only");
nodeRequire.cache[serverOnlyPath] = {
  id: serverOnlyPath,
  filename: serverOnlyPath,
  loaded: true,
  exports: {},
  children: [],
  paths: [],
  // @ts-expect-error minimal Module shape is enough for the cache hit.
  require: nodeRequire,
};

// Point the webhooks store at a temp dir before importing the module.
const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "shotclassify-webhooks-"));
process.env.SHOTCLASSIFY_STORE_DIR = tmpDir;
// This suite uses localhost http servers as webhook targets. The SSRF guard
// blocks loopback in production; flip the test escape hatch on so we
// exercise the rest of the delivery pipeline. The dedicated SSRF tests in
// url-safety.test.mts run without this flag and prove loopback IS blocked.
process.env.SHOTCLASSIFY_WEBHOOK_ALLOW_LOOPBACK = "1";

const { createWebhook, redeliver, listDeliveries } = await import("./webhooks");

function startEchoServer(
  handler: (req: http.IncomingMessage, res: http.ServerResponse) => void,
): Promise<{ url: string; close: () => Promise<void> }> {
  return new Promise((resolve) => {
    const srv = http.createServer(handler);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address() as AddressInfo;
      resolve({
        url: `http://127.0.0.1:${addr.port}/hook`,
        close: () => new Promise((r) => srv.close(() => r())),
      });
    });
  });
}

test("redeliver replays a prior delivery against the current webhook", async () => {
  const calls: { signature: string | undefined; body: string }[] = [];
  const srv = await startEchoServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      calls.push({
        signature: req.headers["x-shotclassify-signature"] as string | undefined,
        body,
      });
      res.statusCode = 200;
      res.end("ok");
    });
  });

  const hook = await createWebhook({
    url: srv.url,
    description: "test",
    events: ["classify.completed"],
  });

  // Seed a prior failed delivery by writing the deliveries file directly.
  const seed = {
    id: "deliv-1",
    webhook_id: hook.id,
    event: "classify.completed",
    url: srv.url,
    status: "failed" as const,
    attempt: 4,
    http_status: 500,
    error: "HTTP 500",
    latency_ms: 12,
    created_at: new Date().toISOString(),
    payload_preview: '{"event":"classify.completed","shot_id":"abc"}',
  };
  await fs.writeFile(
    path.join(tmpDir, "webhook_deliveries.json"),
    JSON.stringify([seed]),
  );

  const result = await redeliver("deliv-1");
  assert.ok(!("error" in result), "should not error");
  if ("error" in result) return;
  assert.equal(result.delivery.webhook_id, hook.id);
  assert.equal(result.delivery.status, "success");
  assert.equal(result.delivery.http_status, 200);
  assert.equal(result.delivery.event, "classify.completed");
  assert.equal(calls.length, 1);
  assert.ok(calls[0].signature?.startsWith("sha256="), "should sign body");
  const parsed = JSON.parse(calls[0].body);
  assert.equal(parsed.replay_of, "deliv-1");

  const all = await listDeliveries(hook.id, 10);
  assert.equal(all.length, 2, "redeliver appended a new delivery");

  await srv.close();
});

test("redeliver returns delivery_not_found when delivery id is unknown", async () => {
  const result = await redeliver("does-not-exist");
  assert.deepEqual(result, { error: "delivery_not_found" });
});

test("listDeliveriesPage filters by status and event and paginates", async () => {
  const { createWebhook, listDeliveriesPage, listDeliveryEvents } = await import(
    "./webhooks"
  );
  const hook = await createWebhook({
    url: "http://127.0.0.1:1/none",
    description: "filter-test",
    events: ["classify.completed"],
  });

  const now = Date.now();
  const seeded = [
    { ev: "classify.completed", st: "success" as const },
    { ev: "classify.completed", st: "failed" as const },
    { ev: "classify.completed", st: "failed" as const },
    { ev: "test.ping", st: "success" as const },
    { ev: "classify.completed", st: "success" as const },
    { ev: "classify.completed", st: "success" as const },
  ].map((s, i) => ({
    id: `f-${i}`,
    webhook_id: hook.id,
    event: s.ev,
    url: "http://127.0.0.1:1/none",
    status: s.st,
    attempt: 1,
    http_status: s.st === "success" ? 200 : 500,
    error: s.st === "failed" ? "HTTP 500" : null,
    latency_ms: 5,
    created_at: new Date(now + i).toISOString(),
    payload_preview: "{}",
  }));
  // Append rather than overwrite so prior tests still pass.
  const existingPath = path.join(tmpDir, "webhook_deliveries.json");
  const existing = JSON.parse(
    (await fs.readFile(existingPath, "utf-8").catch(() => "[]")) || "[]",
  );
  await fs.writeFile(existingPath, JSON.stringify([...existing, ...seeded]));

  const failed = await listDeliveriesPage(hook.id, { status: "failed" });
  assert.equal(failed.total, 2);
  assert.equal(failed.deliveries.length, 2);
  assert.ok(failed.deliveries.every((d) => d.status === "failed"));

  const ping = await listDeliveriesPage(hook.id, { event: "test.ping" });
  assert.equal(ping.total, 1);
  assert.equal(ping.deliveries[0].event, "test.ping");

  const pageA = await listDeliveriesPage(hook.id, { limit: 2, offset: 0 });
  const pageB = await listDeliveriesPage(hook.id, { limit: 2, offset: 2 });
  assert.equal(pageA.limit, 2);
  assert.equal(pageA.deliveries.length, 2);
  assert.equal(pageA.has_more, true);
  assert.equal(pageB.offset, 2);
  assert.notDeepEqual(
    pageA.deliveries.map((d) => d.id),
    pageB.deliveries.map((d) => d.id),
  );

  const events = await listDeliveryEvents(hook.id);
  assert.ok(events.includes("classify.completed"));
  assert.ok(events.includes("test.ping"));
});