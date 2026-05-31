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
