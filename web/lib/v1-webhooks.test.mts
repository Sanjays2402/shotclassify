// Exercises the storage-layer flow used by the new /v1/webhooks endpoints:
// create → list → get → delete. The route handlers themselves are thin
// wrappers around these calls plus the shared `authenticate` helper that
// already has coverage in v1-core.test.mts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { createRequire } from "node:module";

// Neutralize the `server-only` import guard so we can load webhooks.ts in
// a plain node:test process (same trick the existing suite uses).
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

const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "shotclassify-v1-webhooks-"));
process.env.SHOTCLASSIFY_STORE_DIR = tmpDir;

const { createWebhook, listWebhooks, getWebhook, deleteWebhook } = await import(
  "./webhooks"
);

test("v1 webhooks: create then list returns the new subscription", async () => {
  const before = await listWebhooks();
  const hook = await createWebhook({
    url: "https://example.com/incoming",
    description: "ci test hook",
    events: ["classify.completed"],
  });
  assert.ok(hook.id);
  assert.ok(hook.secret.startsWith("whsec_"));
  assert.equal(hook.url, "https://example.com/incoming");
  const after = await listWebhooks();
  assert.equal(after.length, before.length + 1);
  assert.ok(after.find((h) => h.id === hook.id));
});

test("v1 webhooks: get and delete round-trip", async () => {
  const hook = await createWebhook({
    url: "https://example.com/another",
  });
  const fetched = await getWebhook(hook.id);
  assert.ok(fetched);
  assert.equal(fetched?.url, "https://example.com/another");
  const ok = await deleteWebhook(hook.id);
  assert.equal(ok, true);
  const gone = await getWebhook(hook.id);
  assert.equal(gone, null);
  const okAgain = await deleteWebhook(hook.id);
  assert.equal(okAgain, false);
});

test("v1 webhooks: createWebhook rejects non-http URLs", async () => {
  await assert.rejects(
    () => createWebhook({ url: "ftp://example.com/x" }),
    /http/,
  );
});
