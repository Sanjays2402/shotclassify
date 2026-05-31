// Run with: pnpm/npm test (uses npx tsx --test).
import { test } from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";

import {
  createKeyAt,
  rotateKeyAt,
  listKeysAt,
  verifyAndTouchAt,
  normalizeScopes,
  hasScope,
} from "./keystore-core";

async function tmpStore() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "shotclassify-keys-"));
  return { file: path.join(dir, "api_keys.json"), dir };
}

test("rotateKey issues a new plaintext but preserves identity", async () => {
  const { file, dir } = await tmpStore();
  try {
    const { key: k1, plaintext: pt1 } = await createKeyAt(file, "ci");
    assert.ok(pt1.startsWith("sk_live_"));
    assert.equal(k1.usage_count, 0);
    assert.equal(k1.rotated_at ?? null, null);

    // Touch once so we can prove rotate clears last_used_at and keeps usage_count.
    const verified = await verifyAndTouchAt(file, pt1);
    assert.ok(verified);
    assert.equal(verified!.usage_count, 1);
    assert.ok(verified!.last_used_at);

    // Rotate.
    const rotated = await rotateKeyAt(file, k1.id);
    assert.ok(rotated);
    assert.notEqual(rotated!.plaintext, pt1);
    assert.ok(rotated!.plaintext.startsWith("sk_live_"));
    assert.equal(rotated!.key.id, k1.id);
    assert.equal(rotated!.key.name, k1.name);
    assert.equal(rotated!.key.created_at, k1.created_at);
    assert.equal(rotated!.key.usage_count, 1);
    assert.equal(rotated!.key.last_used_at, null);
    assert.ok(rotated!.key.rotated_at);
    assert.equal(rotated!.key.prefix, rotated!.plaintext.slice(0, 12));

    // Old plaintext no longer verifies, new one does.
    const oldOk = await verifyAndTouchAt(file, pt1);
    assert.equal(oldOk, null);
    const newOk = await verifyAndTouchAt(file, rotated!.plaintext);
    assert.ok(newOk);

    // List still shows one key with the same id.
    const all = await listKeysAt(file);
    assert.equal(all.length, 1);
    assert.equal(all[0].id, k1.id);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("rotateKey returns null for unknown id", async () => {
  const { file, dir } = await tmpStore();
  try {
    const out = await rotateKeyAt(file, "nope-not-a-real-id");
    assert.equal(out, null);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("normalizeScopes defaults, dedupes, and read+write implies read", () => {
  assert.deepEqual(normalizeScopes(undefined), ["read", "write"]);
  assert.deepEqual(normalizeScopes([]), ["read", "write"]);
  assert.deepEqual(normalizeScopes(["read"]), ["read"]);
  assert.deepEqual(normalizeScopes(["write"]), ["read", "write"]);
  assert.deepEqual(normalizeScopes(["read", "read", "write"]), ["read", "write"]);
  assert.deepEqual(normalizeScopes(["bogus"]), ["read", "write"]);
});

test("hasScope honors stored scopes and legacy default", () => {
  assert.equal(hasScope({ scopes: ["read"] }, "read"), true);
  assert.equal(hasScope({ scopes: ["read"] }, "write"), false);
  assert.equal(hasScope({ scopes: ["read", "write"] }, "write"), true);
  // legacy / undefined keeps existing behavior (full access).
  assert.equal(hasScope({}, "write"), true);
  assert.equal(hasScope({}, "read"), true);
});

test("createKey persists scopes and rotate preserves them", async () => {
  const { file, dir } = await tmpStore();
  try {
    const { key } = await createKeyAt(file, "readonly-dashboard", ["read"]);
    assert.deepEqual(key.scopes, ["read"]);
    const rotated = await rotateKeyAt(file, key.id);
    assert.deepEqual(rotated!.key.scopes, ["read"]);
    const verified = await verifyAndTouchAt(file, rotated!.plaintext);
    assert.deepEqual(verified!.scopes, ["read"]);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("verifyAndTouch backfills legacy keys missing scopes", async () => {
  const { file, dir } = await tmpStore();
  try {
    const { key, plaintext } = await createKeyAt(file, "legacy");
    // Simulate an old-format on-disk record with no scopes field.
    const raw = await fs.readFile(file, "utf8");
    const parsed = JSON.parse(raw);
    delete parsed[0].scopes;
    await fs.writeFile(file, JSON.stringify(parsed));
    const verified = await verifyAndTouchAt(file, plaintext);
    assert.ok(verified);
    assert.deepEqual(verified!.scopes, ["read", "write"]);
    assert.equal(verified!.id, key.id);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});
