// Pure tests for the notifications-inbox filter breadcrumb chips (F88). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  activeNotifChips,
  countActiveNotifFilters,
  notifKindLabel,
  NOTIF_KIND_LABELS,
  type NotifFilterState,
} from "./notif-filter-chips.ts";

test("activeNotifChips: empty / default state yields no chips", () => {
  for (const f of [
    {},
    { q: "", kind: "all", unreadOnly: false },
    { q: "   ", kind: "", unreadOnly: false },
    { q: null, kind: null, unreadOnly: false },
  ] as NotifFilterState[]) {
    assert.deepEqual(activeNotifChips(f), [], JSON.stringify(f));
  }
});

test("activeNotifChips: search chip truncates a long query, keeps quotes", () => {
  const chips = activeNotifChips({ q: "  webhook timeout error  " });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].key, "q");
  assert.equal(chips[0].field, "Search");
  assert.equal(chips[0].value, '"webhook timeout error"');
  assert.equal(chips[0].label, 'Search: "webhook timeout error"');

  const long = activeNotifChips({
    q: "a really long search string that should be ellipsised in the chip",
  });
  assert.ok(long[0].value.endsWith("\u2026\""), long[0].value);
});

test("activeNotifChips: kind chip uses the human label", () => {
  const chips = activeNotifChips({ kind: "webhook.failed" });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].key, "kind");
  assert.equal(chips[0].value, "Webhook failures");
  assert.equal(chips[0].label, "Kind: Webhook failures");
});

test("activeNotifChips: 'all' / blank kind is not a constraint", () => {
  assert.deepEqual(activeNotifChips({ kind: "all" }), []);
  assert.deepEqual(activeNotifChips({ kind: "  " }), []);
});

test("activeNotifChips: unknown kind falls back to its raw value", () => {
  const chips = activeNotifChips({ kind: "future.kind" });
  assert.equal(chips[0].value, "future.kind");
  assert.equal(chips[0].label, "Kind: future.kind");
});

test("activeNotifChips: unread toggle is a value-less chip", () => {
  const chips = activeNotifChips({ unreadOnly: true });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].key, "unread");
  assert.equal(chips[0].value, "only");
  assert.equal(chips[0].label, "Unread only");
  // A false toggle adds nothing.
  assert.deepEqual(activeNotifChips({ unreadOnly: false }), []);
});

test("activeNotifChips: order is search, then kind, then unread", () => {
  const chips = activeNotifChips({
    q: "fail",
    kind: "system",
    unreadOnly: true,
  });
  assert.deepEqual(
    chips.map((c) => c.key),
    ["q", "kind", "unread"],
  );
});

test("countActiveNotifFilters: counts the active constraints", () => {
  assert.equal(countActiveNotifFilters({}), 0);
  assert.equal(countActiveNotifFilters({ q: "x" }), 1);
  assert.equal(
    countActiveNotifFilters({ q: "x", kind: "system", unreadOnly: true }),
    3,
  );
});

test("notifKindLabel: maps every known kind + falls back", () => {
  assert.equal(notifKindLabel("classify.completed"), "Classifications");
  assert.equal(notifKindLabel("webhook.failed"), "Webhook failures");
  assert.equal(notifKindLabel("system"), "System");
  assert.equal(notifKindLabel("mystery"), "mystery");
  // Every label table entry is non-empty.
  for (const [k, v] of Object.entries(NOTIF_KIND_LABELS)) {
    assert.ok(v.length > 0, k);
  }
});
