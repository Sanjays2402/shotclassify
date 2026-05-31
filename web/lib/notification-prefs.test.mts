// Tests for the notification preferences store and its enforcement
// inside notify(). Uses a fresh tempdir so we never pollute real data.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const TMP = mkdtempSync(path.join(tmpdir(), "sc-prefs-"));
process.env.SHOTCLASSIFY_STORE_DIR = TMP;

const prefs = await import("./notification-prefs.ts");
const notifs = await import("./notifications.ts");

test("prefs: defaults enable every known kind", async () => {
  const p = await prefs.readPrefs();
  assert.equal(p.enabled["classify.completed"], true);
  assert.equal(p.enabled["webhook.failed"], true);
  assert.equal(p.enabled.system, true);
  assert.equal(p.updated_at, null);
});

test("prefs: writePrefs persists partial updates and stamps updated_at", async () => {
  const next = await prefs.writePrefs({ "classify.completed": false });
  assert.equal(next.enabled["classify.completed"], false);
  assert.equal(next.enabled["webhook.failed"], true);
  assert.ok(next.updated_at);
  const reread = await prefs.readPrefs();
  assert.equal(reread.enabled["classify.completed"], false);
});

test("notify: muted kind returns null and is not stored", async () => {
  const before = (await notifs.listNotifications()).length;
  const result = await notifs.notify({
    kind: "classify.completed",
    title: "muted",
    body: "should not appear",
  });
  assert.equal(result, null);
  const after = (await notifs.listNotifications()).length;
  assert.equal(after, before);
});

test("notify: enabled kind still records normally", async () => {
  const result = await notifs.notify({
    kind: "system",
    title: "still on",
    body: "should appear",
  });
  assert.ok(result);
  const items = await notifs.listNotifications();
  assert.equal(items[0].title, "still on");
});

test("prefs: re-enabling restores notify() persistence", async () => {
  await prefs.writePrefs({ "classify.completed": true });
  const result = await notifs.notify({
    kind: "classify.completed",
    title: "back on",
    body: "now persisted",
  });
  assert.ok(result);
});
