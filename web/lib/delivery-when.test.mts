// Pure tests for the /webhooks deliveries relative-When label (F129). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { deliveryRelativeLabel } from "./delivery-when.ts";

// A fixed "now" so the buckets are deterministic.
const NOW = Date.parse("2026-06-27T19:00:00Z");

test("deliveryRelativeLabel: a few minutes ago", () => {
  assert.equal(
    deliveryRelativeLabel("2026-06-27T18:57:00Z", NOW),
    "3m ago",
  );
});

test("deliveryRelativeLabel: hours ago", () => {
  assert.equal(
    deliveryRelativeLabel("2026-06-27T16:00:00Z", NOW),
    "3h ago",
  );
});

test("deliveryRelativeLabel: sub-minute collapses to just now", () => {
  assert.equal(
    deliveryRelativeLabel("2026-06-27T18:59:40Z", NOW),
    "just now",
  );
});

test("deliveryRelativeLabel: a future timestamp is clamped to just now", () => {
  assert.equal(
    deliveryRelativeLabel("2026-06-27T19:05:00Z", NOW),
    "just now",
  );
});

test("deliveryRelativeLabel: days ago", () => {
  assert.equal(
    deliveryRelativeLabel("2026-06-25T19:00:00Z", NOW),
    "2d ago",
  );
});

test("deliveryRelativeLabel: null / blank / unparseable -> empty string", () => {
  assert.equal(deliveryRelativeLabel(null, NOW), "");
  assert.equal(deliveryRelativeLabel(undefined, NOW), "");
  assert.equal(deliveryRelativeLabel("", NOW), "");
  assert.equal(deliveryRelativeLabel("   ", NOW), "");
  assert.equal(deliveryRelativeLabel("not a date", NOW), "");
});

test("deliveryRelativeLabel: a non-finite now yields empty (defensive)", () => {
  assert.equal(deliveryRelativeLabel("2026-06-27T18:57:00Z", NaN), "");
});
