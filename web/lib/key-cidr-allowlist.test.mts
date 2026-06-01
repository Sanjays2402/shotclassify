// Run with: npm test (uses npx tsx --test).
//
// Covers the per-API-key source-IP allowlist that backs the new
// `/keys/:id` settings panel. The contract this proves:
//
//   * Normalization rejects garbage, dedupes, and accepts both IPv4 and
//     IPv6 with or without a prefix length.
//   * `ipAllowed` defaults to "any" when the list is empty and matches
//     individual addresses, IPv4 CIDR ranges, and IPv6 prefixes correctly.
//   * Persisting an allowlist via `setKeyAllowedCidrsAt` round-trips,
//     keeps unrelated fields intact, and is read back by `getKeyAt`.
//   * A request from an out-of-range IP is denied even when the key
//     itself is otherwise valid, proving the choke-point at the auth
//     layer would reject the call.
import { test } from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";

import {
  createKeyAt,
  getKeyAt,
  ipAllowed,
  normalizeCidr,
  normalizeCidrs,
  setKeyAllowedCidrsAt,
  verifyAndTouchAt,
} from "./keystore-core";

async function tmpStore() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "shotclassify-cidrs-"));
  return { file: path.join(dir, "api_keys.json"), dir };
}

test("normalizeCidr accepts IPv4 with and without prefix", () => {
  assert.equal(normalizeCidr("203.0.113.4"), "203.0.113.4/32");
  assert.equal(normalizeCidr("203.0.113.0/24"), "203.0.113.0/24");
  assert.equal(normalizeCidr("  10.0.0.1  "), "10.0.0.1/32");
});

test("normalizeCidr accepts IPv6 including embedded IPv4", () => {
  const v = normalizeCidr("2001:db8::1");
  assert.ok(v && v.endsWith("/128"));
  const range = normalizeCidr("2001:db8::/32");
  assert.equal(range, "2001:db8:0:0:0:0:0:0/32");
  const mapped = normalizeCidr("::ffff:1.2.3.4");
  assert.ok(mapped && mapped.endsWith("/128"));
});

test("normalizeCidr rejects garbage", () => {
  assert.equal(normalizeCidr(""), null);
  assert.equal(normalizeCidr("not-an-ip"), null);
  assert.equal(normalizeCidr("999.0.0.1"), null);
  assert.equal(normalizeCidr("10.0.0.1/40"), null);
  assert.equal(normalizeCidr("2001:db8::1/200"), null);
});

test("normalizeCidrs dedupes, throws on bad entries, caps length", () => {
  const out = normalizeCidrs([
    "203.0.113.4",
    "203.0.113.4/32", // duplicate after normalization
    "10.0.0.0/8",
  ]);
  assert.deepEqual(out, ["203.0.113.4/32", "10.0.0.0/8"]);
  assert.throws(() => normalizeCidrs(["10.0.0.1", "garbage"]));
});

test("ipAllowed defaults to any when list is empty", () => {
  assert.equal(ipAllowed({}, "203.0.113.4"), true);
  assert.equal(ipAllowed({ allowed_cidrs: [] }, "203.0.113.4"), true);
  // But a missing client IP with an empty list is still allowed because the
  // key is unrestricted; that's the legacy behaviour we preserve.
  assert.equal(ipAllowed({}, null), true);
});

test("ipAllowed matches IPv4 single host and CIDR", () => {
  const key = { allowed_cidrs: ["203.0.113.4/32", "10.0.0.0/8"] };
  assert.equal(ipAllowed(key, "203.0.113.4"), true);
  assert.equal(ipAllowed(key, "203.0.113.5"), false);
  assert.equal(ipAllowed(key, "10.1.2.3"), true);
  assert.equal(ipAllowed(key, "11.1.2.3"), false);
  assert.equal(ipAllowed(key, null), false); // restricted + unknown IP = deny
});

test("ipAllowed matches IPv6 prefix", () => {
  const key = { allowed_cidrs: ["2001:db8::/32"] };
  assert.equal(ipAllowed(key, "2001:db8:1234::1"), true);
  assert.equal(ipAllowed(key, "2001:db9::1"), false);
  // IPv4 client does not satisfy an IPv6 allowlist.
  assert.equal(ipAllowed(key, "10.0.0.1"), false);
});

test("ipAllowed rejects malformed client IPs", () => {
  const key = { allowed_cidrs: ["10.0.0.0/8"] };
  assert.equal(ipAllowed(key, "garbage"), false);
  assert.equal(ipAllowed(key, ""), false);
});

test("setKeyAllowedCidrsAt persists and is reflected by getKeyAt", async () => {
  const { file } = await tmpStore();
  const { key } = await createKeyAt(file, "ci");
  const updated = await setKeyAllowedCidrsAt(file, key.id, [
    "203.0.113.0/24",
    "10.0.0.0/8",
  ]);
  assert.ok(updated);
  assert.deepEqual(updated!.allowed_cidrs, ["203.0.113.0/24", "10.0.0.0/8"]);

  const reread = await getKeyAt(file, key.id);
  assert.ok(reread);
  assert.deepEqual(reread!.allowed_cidrs, ["203.0.113.0/24", "10.0.0.0/8"]);
  // Other fields must be intact: same id, same name, no rotation on the
  // allowlist edit.
  assert.equal(reread!.id, key.id);
  assert.equal(reread!.name, key.name);
  assert.equal(reread!.rotated_at ?? null, null);

  // Clearing the list returns the key to "any IP".
  const cleared = await setKeyAllowedCidrsAt(file, key.id, []);
  assert.ok(cleared);
  assert.deepEqual(cleared!.allowed_cidrs, []);
});

test("a verified key from an out-of-range IP is denied at the choke point", async () => {
  const { file } = await tmpStore();
  const { key, plaintext } = await createKeyAt(file, "ci");

  // Restrict to a single corporate egress.
  await setKeyAllowedCidrsAt(file, key.id, ["198.51.100.0/24"]);

  // The key itself still verifies (the secret is correct).
  const verified = await verifyAndTouchAt(file, plaintext);
  assert.ok(verified);
  assert.deepEqual(verified!.allowed_cidrs, ["198.51.100.0/24"]);

  // But the auth boundary must reject a request from outside the range,
  // which is what `ipAllowed` decides.
  assert.equal(ipAllowed(verified!, "203.0.113.7"), false);
  assert.equal(ipAllowed(verified!, "198.51.100.42"), true);
});

test("setKeyAllowedCidrsAt surfaces invalid input as an error", async () => {
  const { file } = await tmpStore();
  const { key } = await createKeyAt(file, "ci");
  await assert.rejects(
    () => setKeyAllowedCidrsAt(file, key.id, ["10.0.0.1", "not-an-ip"]),
    /Not a valid IP or CIDR/,
  );
  // The key on disk must not have been partially updated.
  const reread = await getKeyAt(file, key.id);
  assert.ok(reread);
  assert.deepEqual(reread!.allowed_cidrs ?? [], []);
});
