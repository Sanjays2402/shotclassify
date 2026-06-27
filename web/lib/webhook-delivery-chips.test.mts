// Pure tests for the /webhooks recent-deliveries filter + breadcrumb (F92).
// No DOM. Mirrors lib/notif-filter-chips.test.mts (F88).
import test from "node:test";
import assert from "node:assert/strict";

import {
  activeDeliveryChips,
  countActiveDeliveryFilters,
  deliveryFilterCountLabel,
  deliveryStatusCounts,
  distinctDeliveryEvents,
  distinctEventCountLabel,
  filterDeliveries,
  deliveryStatusLabel,
  statusSwatchAria,
  DELIVERY_STATUSES,
  DELIVERY_STATUS_LABELS,
  type DeliveryLike,
  type WebhookDeliveryFilterState,
} from "./webhook-delivery-chips.ts";

const SAMPLE: DeliveryLike[] = [
  { status: "success", event: "classify.completed" },
  { status: "failed", event: "classify.completed" },
  { status: "pending", event: "webhook.test" },
  { status: "success", event: "webhook.test" },
];

test("DELIVERY_STATUSES + labels are stable, failures-first ordering", () => {
  assert.deepEqual([...DELIVERY_STATUSES], ["success", "failed", "pending"]);
  assert.equal(DELIVERY_STATUS_LABELS.success, "Success");
  assert.equal(DELIVERY_STATUS_LABELS.failed, "Failed");
  assert.equal(DELIVERY_STATUS_LABELS.pending, "Pending");
});

test("deliveryStatusLabel: known -> title-case, unknown -> raw", () => {
  assert.equal(deliveryStatusLabel("failed"), "Failed");
  assert.equal(deliveryStatusLabel("retrying"), "retrying");
});

test("distinctDeliveryEvents: sorted, de-duped, blanks skipped", () => {
  assert.deepEqual(distinctDeliveryEvents(SAMPLE), [
    "classify.completed",
    "webhook.test",
  ]);
  assert.deepEqual(
    distinctDeliveryEvents([
      { status: "success", event: " z.event " },
      { status: "failed", event: "a.event" },
      { status: "pending", event: "" },
      { status: "pending", event: "a.event" },
    ]),
    ["a.event", "z.event"],
  );
  assert.deepEqual(distinctDeliveryEvents([]), []);
  assert.deepEqual(distinctDeliveryEvents(null as never), []);
});

test("filterDeliveries: inert filter returns every row (new array)", () => {
  for (const f of [
    {},
    { status: "all", event: "all" },
    { status: "", event: null },
    { status: "   ", event: undefined },
  ] as WebhookDeliveryFilterState[]) {
    const out = filterDeliveries(SAMPLE, f);
    assert.equal(out.length, SAMPLE.length, JSON.stringify(f));
    assert.notEqual(out, SAMPLE, "returns a copy, not the same reference");
  }
});

test("filterDeliveries: status only", () => {
  const out = filterDeliveries(SAMPLE, { status: "success" });
  assert.equal(out.length, 2);
  assert.ok(out.every((d) => d.status === "success"));
});

test("filterDeliveries: event only", () => {
  const out = filterDeliveries(SAMPLE, { event: "webhook.test" });
  assert.equal(out.length, 2);
  assert.ok(out.every((d) => d.event === "webhook.test"));
});

test("filterDeliveries: status AND event both constrain", () => {
  const out = filterDeliveries(SAMPLE, {
    status: "success",
    event: "webhook.test",
  });
  assert.equal(out.length, 1);
  assert.equal(out[0].status, "success");
  assert.equal(out[0].event, "webhook.test");
});

test("filterDeliveries: a non-matching combo yields []", () => {
  const out = filterDeliveries(SAMPLE, {
    status: "failed",
    event: "webhook.test",
  });
  assert.deepEqual(out, []);
});

test("filterDeliveries: non-array input is safe", () => {
  assert.deepEqual(filterDeliveries(null as never, { status: "failed" }), []);
});

test("activeDeliveryChips: empty / default state yields no chips", () => {
  for (const f of [
    {},
    { status: "all", event: "all" },
    { status: "", event: null },
  ] as WebhookDeliveryFilterState[]) {
    assert.deepEqual(activeDeliveryChips(f), [], JSON.stringify(f));
  }
});

test("activeDeliveryChips: status chip uses the title-case label", () => {
  const chips = activeDeliveryChips({ status: "failed" });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].key, "status");
  assert.equal(chips[0].field, "Status");
  assert.equal(chips[0].value, "Failed");
  assert.equal(chips[0].label, "Status: Failed");
});

test("activeDeliveryChips: event chip keeps the raw event name", () => {
  const chips = activeDeliveryChips({ event: "classify.completed" });
  assert.equal(chips.length, 1);
  assert.equal(chips[0].key, "event");
  assert.equal(chips[0].field, "Event");
  assert.equal(chips[0].value, "classify.completed");
});

test("activeDeliveryChips: status before event (triage order)", () => {
  const chips = activeDeliveryChips({
    status: "pending",
    event: "webhook.test",
  });
  assert.deepEqual(
    chips.map((c) => c.key),
    ["status", "event"],
  );
});

test("countActiveDeliveryFilters: counts the active constraints", () => {
  assert.equal(countActiveDeliveryFilters({}), 0);
  assert.equal(countActiveDeliveryFilters({ status: "failed" }), 1);
  assert.equal(
    countActiveDeliveryFilters({ status: "failed", event: "a.b" }),
    2,
  );
});

test("deliveryFilterCountLabel: narrowed view names shown-of-total", () => {
  assert.equal(deliveryFilterCountLabel(3, 10), "Filtering 3 of 10 deliveries");
  assert.equal(deliveryFilterCountLabel(0, 4), "Filtering 0 of 4 deliveries");
});

test("deliveryFilterCountLabel: nothing hidden -> null (no inert noise)", () => {
  assert.equal(deliveryFilterCountLabel(10, 10), null);
  assert.equal(deliveryFilterCountLabel(0, 0), null);
});

test("deliveryFilterCountLabel: singular noun at a total of one", () => {
  assert.equal(deliveryFilterCountLabel(0, 1), "Filtering 0 of 1 delivery");
});

test("deliveryFilterCountLabel: defensive against bad / over-range input", () => {
  // shown > total clamps to total -> reads as not-narrowed -> null.
  assert.equal(deliveryFilterCountLabel(12, 10), null);
  // negatives floor at zero.
  assert.equal(deliveryFilterCountLabel(-3, 5), "Filtering 0 of 5 deliveries");
  // non-finite inputs no-op.
  assert.equal(deliveryFilterCountLabel(NaN, 5), null);
  assert.equal(deliveryFilterCountLabel(2, Infinity), null);
  // fractional inputs truncate.
  assert.equal(deliveryFilterCountLabel(2.9, 9.4), "Filtering 2 of 9 deliveries");
});

test("deliveryStatusCounts: tallies into all three statuses, stable order", () => {
  const counts = deliveryStatusCounts(SAMPLE);
  assert.deepEqual(
    counts.map((c) => c.status),
    ["success", "failed", "pending"],
  );
  assert.deepEqual(
    counts.map((c) => c.count),
    [2, 1, 1],
  );
  // Labels come from the canonical map.
  assert.deepEqual(
    counts.map((c) => c.label),
    ["Success", "Failed", "Pending"],
  );
});

test("deliveryStatusCounts: absent statuses report zero, never omitted", () => {
  const counts = deliveryStatusCounts([
    { status: "success", event: "a" },
    { status: "success", event: "b" },
  ]);
  assert.deepEqual(
    counts.map((c) => c.count),
    [2, 0, 0],
  );
  // Always exactly the three known statuses.
  assert.equal(counts.length, DELIVERY_STATUSES.length);
});

test("deliveryStatusCounts: ignores unknown statuses + prototype keys", () => {
  const counts = deliveryStatusCounts([
    { status: "retrying", event: "a" },
    { status: "toString", event: "b" }, // would corrupt a naive `in` tally
    { status: " failed ", event: "c" }, // trimmed -> counts
    { status: "failed", event: "d" },
  ]);
  const byStatus = Object.fromEntries(counts.map((c) => [c.status, c.count]));
  assert.equal(byStatus.success, 0);
  assert.equal(byStatus.failed, 2);
  assert.equal(byStatus.pending, 0);
});

test("deliveryStatusCounts: empty / non-array input is all zeros", () => {
  for (const c of deliveryStatusCounts([])) assert.equal(c.count, 0);
  for (const c of deliveryStatusCounts(null as never)) assert.equal(c.count, 0);
});

test("distinctEventCountLabel: counts the distinct events seen", () => {
  assert.equal(distinctEventCountLabel(["a", "b", "c"]), "3 seen");
  assert.equal(distinctEventCountLabel(["only"]), "1 seen");
});

test("distinctEventCountLabel: empty / non-array -> null (inert noise)", () => {
  assert.equal(distinctEventCountLabel([]), null);
  assert.equal(distinctEventCountLabel(null), null);
  assert.equal(distinctEventCountLabel(undefined), null);
  assert.equal(distinctEventCountLabel("nope" as never), null);
});

test("distinctEventCountLabel: composes with distinctDeliveryEvents", () => {
  // End-to-end: derive the distinct list from raw deliveries, then label it.
  const events = distinctDeliveryEvents([
    { status: "success", event: "classify.completed" },
    { status: "failed", event: "classify.completed" }, // dup -> one
    { status: "pending", event: "shot.created" },
  ]);
  assert.equal(distinctEventCountLabel(events), "2 seen");
});

test("statusSwatchAria: inactive swatch announces the show-only action + count", () => {
  const { ariaLabel, title } = statusSwatchAria("Success", 3, false);
  assert.equal(ariaLabel, "Success, 3 deliveries. Show only success deliveries");
  assert.equal(title, "Show only success deliveries");
});

test("statusSwatchAria: active swatch announces the clear action", () => {
  const { ariaLabel, title } = statusSwatchAria("Failed", 5, true);
  assert.equal(ariaLabel, "Failed, 5 deliveries. Clear the failed filter");
  assert.equal(title, "Clear the failed filter");
});

test("statusSwatchAria: singular delivery noun at a count of one", () => {
  const { ariaLabel } = statusSwatchAria("Pending", 1, false);
  assert.equal(ariaLabel, "Pending, 1 delivery. Show only pending deliveries");
});

test("statusSwatchAria: zero / non-finite / negative counts floor to a sane phrase", () => {
  assert.equal(
    statusSwatchAria("Success", 0, false).ariaLabel,
    "Success, 0 deliveries. Show only success deliveries",
  );
  assert.equal(
    statusSwatchAria("Success", NaN, false).ariaLabel,
    "Success, 0 deliveries. Show only success deliveries",
  );
  assert.equal(
    statusSwatchAria("Success", -4, false).ariaLabel,
    "Success, 0 deliveries. Show only success deliveries",
  );
  // fractional counts truncate toward zero.
  assert.equal(
    statusSwatchAria("Success", 2.9, false).ariaLabel,
    "Success, 2 deliveries. Show only success deliveries",
  );
});

test("statusSwatchAria: blank label degrades to a generic 'status' name", () => {
  const { ariaLabel, title } = statusSwatchAria("   ", 2, false);
  assert.equal(ariaLabel, "status, 2 deliveries. Show only status deliveries");
  assert.equal(title, "Show only status deliveries");
});

