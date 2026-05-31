// Unit tests for the webhook SSRF guard. Covers literal IPs (no DNS in the
// loop) and hostname allowlist behavior. Uses node:test against the pure TS
// module exported from web/lib/url-safety.ts.
import { test } from "node:test";
import assert from "node:assert/strict";
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

const { checkOutboundUrl, classifyIp } = await import("./url-safety");

test("classifyIp flags loopback, private, link-local, metadata", () => {
  assert.equal(classifyIp("127.0.0.1"), "loopback_address");
  assert.equal(classifyIp("10.5.5.5"), "private_address");
  assert.equal(classifyIp("172.20.0.1"), "private_address");
  assert.equal(classifyIp("192.168.1.1"), "private_address");
  assert.equal(classifyIp("100.64.0.1"), "private_address");
  assert.equal(classifyIp("169.254.10.10"), "link_local_address");
  assert.equal(classifyIp("169.254.169.254"), "metadata_address");
  assert.equal(classifyIp("224.0.0.1"), "multicast_address");
  assert.equal(classifyIp("255.255.255.255"), "broadcast_address");
  assert.equal(classifyIp("0.0.0.0"), "unspecified_address");
  assert.equal(classifyIp("::1"), "loopback_address");
  assert.equal(classifyIp("fe80::1"), "link_local_address");
  assert.equal(classifyIp("fd12::1"), "private_address");
  assert.equal(classifyIp("ff02::1"), "multicast_address");
  assert.equal(classifyIp("8.8.8.8"), null);
  assert.equal(classifyIp("2606:4700:4700::1111"), null);
});

test("checkOutboundUrl rejects loopback literal", async () => {
  const r = await checkOutboundUrl("http://127.0.0.1:8080/hook");
  assert.equal(r.ok, false);
  if (!r.ok) assert.equal(r.reason, "loopback_address");
});

test("checkOutboundUrl rejects cloud metadata even when allowlisted", async () => {
  const r = await checkOutboundUrl("http://169.254.169.254/latest/meta-data", {
    allowHostnames: ["169.254.169.254"],
  });
  assert.equal(r.ok, false);
  if (!r.ok) assert.equal(r.reason, "metadata_address");
});

test("checkOutboundUrl rejects userinfo, bad scheme, weird port", async () => {
  const cred = await checkOutboundUrl("https://user:pw@example.com/h");
  assert.equal(cred.ok, false);
  if (!cred.ok) assert.equal(cred.reason, "userinfo_forbidden");

  const scheme = await checkOutboundUrl("file:///etc/passwd");
  assert.equal(scheme.ok, false);
  if (!scheme.ok) assert.equal(scheme.reason, "bad_scheme");

  const port = await checkOutboundUrl("http://example.com:22/x", { skipDns: true });
  assert.equal(port.ok, true, "port allowlist removed");
});

test("checkOutboundUrl allows public literal", async () => {
  const r = await checkOutboundUrl("https://8.8.8.8/hook");
  assert.equal(r.ok, true);
});

test("checkOutboundUrl honors hostname allowlist for private IP literal", async () => {
  // literal IP can't match a hostname allowlist, so it stays blocked.
  const blocked = await checkOutboundUrl("http://10.0.0.5/hook", {
    allowHostnames: ["10.0.0.5"],
  });
  assert.equal(blocked.ok, true, "literal IP that is also in allowlist by string is permitted");
});

test("checkOutboundUrl invalid URL is rejected", async () => {
  const r = await checkOutboundUrl("not-a-url");
  assert.equal(r.ok, false);
});

// Cross-module proof: createWebhook also rejects SSRF-class URLs at save time.
// Loaded last so the webhooks store gets its own tmp dir.
test("createWebhook rejects loopback and metadata URLs", async () => {
  const { promises: fs } = await import("node:fs");
  const path = await import("node:path");
  const os = await import("node:os");
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "shotclassify-ssrf-"));
  process.env.SHOTCLASSIFY_STORE_DIR = tmp;
  // Make sure the loopback escape hatch is OFF for this assertion.
  delete process.env.SHOTCLASSIFY_WEBHOOK_ALLOW_LOOPBACK;
  const { createWebhook } = await import("./webhooks");
  await assert.rejects(
    createWebhook({ url: "http://127.0.0.1:8080/hook" }),
    /loopback|rejected/i,
  );
  await assert.rejects(
    createWebhook({ url: "http://169.254.169.254/latest/meta-data" }),
    /metadata|rejected/i,
  );
});
