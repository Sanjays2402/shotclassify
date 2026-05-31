// Smoke tests for the file-backed notification store.
// Uses a tempdir as SHOTCLASSIFY_STORE_DIR so we never pollute real data.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const TMP = mkdtempSync(path.join(tmpdir(), "sc-notifs-"));
process.env.SHOTCLASSIFY_STORE_DIR = TMP;

const mod = await import("./notifications.ts");

test("notifications: empty store returns []", async () => {
  const items = await mod.listNotifications();
  assert.equal(items.length, 0);
  assert.equal(await mod.unreadCount(), 0);
});

test("notifications: notify, read, delete round-trip", async () => {
  const a = await mod.notify({
    kind: "system",
    title: "Hello",
    body: "World",
    href: "/x",
  });
  const b = await mod.notify({
    kind: "classify.completed",
    title: "Classified as menu",
    body: "Confidence 92%.",
    href: "/shots/abc",
  });
  let items = await mod.listNotifications();
  assert.equal(items.length, 2);
  // newest first
  assert.equal(items[0].id, b.id);
  assert.equal(await mod.unreadCount(), 2);

  const updated = await mod.markRead(a.id);
  assert.ok(updated && updated.read_at);
  assert.equal(await mod.unreadCount(), 1);

  const n = await mod.markAllRead();
  assert.equal(n, 1);
  assert.equal(await mod.unreadCount(), 0);

  const ok = await mod.deleteOne(b.id);
  assert.equal(ok, true);
  items = await mod.listNotifications();
  assert.equal(items.length, 1);
  assert.equal(items[0].id, a.id);

  const cleared = await mod.clearAll();
  assert.equal(cleared, 1);
  assert.equal((await mod.listNotifications()).length, 0);
});

test("notifications: bad ids fail gracefully", async () => {
  assert.equal(await mod.markRead("nope"), null);
  assert.equal(await mod.deleteOne("nope"), false);
});

test("notifications: notifyClassifyCompleted derives a readable title", async () => {
  await mod.clearAll();
  await mod.notifyClassifyCompleted({
    shot_id: "shot_123",
    primary_category: "leaderboard",
    confidence: 0.87,
  });
  const items = await mod.listNotifications();
  assert.equal(items.length, 1);
  assert.match(items[0].title, /leaderboard/);
  assert.match(items[0].body, /87%/);
  assert.equal(items[0].href, "/shots/shot_123");
});

test.after(() => {
  rmSync(TMP, { recursive: true, force: true });
});
