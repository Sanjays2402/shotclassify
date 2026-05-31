import test from "node:test";
import assert from "node:assert/strict";

import { matchesNotif, paginateNotifs, parseNotifQuery } from "./notif-query.ts";
import type { Notification } from "./notifications.ts";

function notif(
  i: number,
  over: Partial<Notification> = {},
): Notification {
  return {
    id: `n${i}`,
    kind: "classify.completed",
    title: `Shot ${i} done`,
    body: `Classified shot number ${i}`,
    href: null,
    created_at: new Date(2026, 0, i + 1).toISOString(),
    read_at: null,
    ...over,
  };
}

test("matchesNotif: text query hits title/body/kind, case-insensitive", () => {
  const n = notif(7, { title: "Webhook delivery failed", body: "boom" });
  assert.equal(matchesNotif(n, { q: "webhook" }), true);
  assert.equal(matchesNotif(n, { q: "BOOM" }), true);
  assert.equal(matchesNotif(n, { q: "nope" }), false);
});

test("matchesNotif: kind filter respects 'all' and unknown", () => {
  const a = notif(1, { kind: "classify.completed" });
  const b = notif(2, { kind: "webhook.failed" });
  assert.equal(matchesNotif(a, { kind: "all" }), true);
  assert.equal(matchesNotif(b, { kind: "garbage" }), true);
  assert.equal(matchesNotif(a, { kind: "webhook.failed" }), false);
  assert.equal(matchesNotif(b, { kind: "webhook.failed" }), true);
});

test("matchesNotif: unread_only drops read items", () => {
  const a = notif(1, { read_at: null });
  const b = notif(2, { read_at: new Date().toISOString() });
  assert.equal(matchesNotif(a, { unread_only: true }), true);
  assert.equal(matchesNotif(b, { unread_only: true }), false);
});

test("paginateNotifs: returns page slice and next_cursor", () => {
  const all = Array.from({ length: 60 }, (_, i) => notif(i));
  const p1 = paginateNotifs(all, { limit: 25, cursor: 0 });
  assert.equal(p1.items.length, 25);
  assert.equal(p1.matched, 60);
  assert.equal(p1.total, 60);
  assert.equal(p1.next_cursor, 25);

  const p3 = paginateNotifs(all, { limit: 25, cursor: 50 });
  assert.equal(p3.items.length, 10);
  assert.equal(p3.next_cursor, null);
});

test("paginateNotifs: applies filter before pagination", () => {
  const all = [
    notif(1, { kind: "classify.completed", title: "alpha" }),
    notif(2, { kind: "webhook.failed", title: "beta" }),
    notif(3, { kind: "system", title: "alpha system" }),
    notif(4, { kind: "classify.completed", title: "alpha again" }),
  ];
  const res = paginateNotifs(all, { q: "alpha", limit: 10 });
  assert.equal(res.matched, 3);
  assert.equal(res.items.length, 3);
  // Unread/all counters are global, not filtered.
  assert.equal(res.total, 4);
});

test("paginateNotifs: clamps limit and floors cursor", () => {
  const all = Array.from({ length: 10 }, (_, i) => notif(i));
  const wide = paginateNotifs(all, { limit: 9999 });
  assert.equal(wide.items.length, 10);
  const negative = paginateNotifs(all, { limit: 0, cursor: -5 });
  assert.equal(negative.items.length, 1);
});

test("parseNotifQuery: maps URLSearchParams safely", () => {
  const u = new URLSearchParams(
    "q=hello&kind=webhook.failed&unread_only=1&cursor=25&limit=10",
  );
  const p = parseNotifQuery(u);
  assert.equal(p.q, "hello");
  assert.equal(p.kind, "webhook.failed");
  assert.equal(p.unread_only, true);
  assert.equal(p.cursor, 25);
  assert.equal(p.limit, 10);

  const empty = parseNotifQuery(new URLSearchParams(""));
  assert.equal(empty.cursor, 0);
  assert.equal(empty.limit, 25);
  assert.equal(empty.unread_only, false);
});
