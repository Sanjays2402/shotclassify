// Tests for the upgrade-intent store and plan catalog. Uses a fresh
// tempdir so test runs don't pollute real storage.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const TMP = mkdtempSync(path.join(tmpdir(), "sc-billing-"));
process.env.SHOTCLASSIFY_STORE_DIR = TMP;

const billing = await import("./billing.ts");

test("plans: free, pro, team are present and ordered for display", () => {
  assert.equal(billing.PLANS.length, 3);
  assert.deepEqual(
    billing.PLANS.map((p) => p.id),
    ["free", "pro", "team"],
  );
  const pro = billing.getPlan("pro");
  assert.ok(pro);
  assert.equal(pro!.price_monthly_usd, 29);
  assert.equal(billing.getPlan("nope"), null);
});

test("recordIntent: rejects unknown plan", async () => {
  const r = await billing.recordIntent({ plan: "enterprise" });
  assert.equal(r.ok, false);
  if (!r.ok) assert.equal(r.error.code, "unknown_plan");
});

test("recordIntent: rejects free as an upgrade target", async () => {
  const r = await billing.recordIntent({ plan: "free" });
  assert.equal(r.ok, false);
  if (!r.ok) assert.equal(r.error.code, "free_plan");
});

test("recordIntent: rejects malformed email but accepts empty", async () => {
  const bad = await billing.recordIntent({ plan: "pro", email: "not-an-email" });
  assert.equal(bad.ok, false);
  if (!bad.ok) assert.equal(bad.error.code, "bad_email");
  const ok = await billing.recordIntent({ plan: "pro", email: "  " });
  assert.equal(ok.ok, true);
});

test("recordIntent: persists to JSON and listIntents returns it newest-first", async () => {
  const a = await billing.recordIntent({
    plan: "pro",
    email: "a@example.com",
    company: "Acme",
    note: "Need higher limits.",
    source: "test",
  });
  assert.equal(a.ok, true);
  const b = await billing.recordIntent({
    plan: "team",
    email: "b@example.com",
  });
  assert.equal(b.ok, true);

  const list = await billing.listIntents();
  // listIntents is newest first; b was recorded after a.
  assert.ok(list.length >= 2);
  assert.equal(list[0].plan, "team");

  // File on disk reflects what we wrote.
  const raw = readFileSync(billing.intentStorePath(), "utf8");
  const parsed = JSON.parse(raw) as { intents: Array<{ plan: string }> };
  assert.ok(parsed.intents.some((i) => i.plan === "pro"));
  assert.ok(parsed.intents.some((i) => i.plan === "team"));
});

test("recordIntent: trims long note to a sane cap", async () => {
  const big = "x".repeat(5000);
  const r = await billing.recordIntent({ plan: "pro", note: big });
  assert.equal(r.ok, true);
  if (r.ok) assert.equal(r.intent.note!.length, 1000);
});
