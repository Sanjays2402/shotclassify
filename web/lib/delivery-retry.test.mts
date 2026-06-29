// Pure tests for the /webhooks delivery retry helper (F147). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  canRetryDelivery,
  retryButtonLabel,
  retryAriaLabel,
  retryToast,
} from "./delivery-retry.ts";

test("canRetryDelivery: only failed deliveries with an id", () => {
  assert.equal(canRetryDelivery({ id: "d1", status: "failed", event: "x" }), true);
  assert.equal(canRetryDelivery({ id: "d1", status: "success", event: "x" }), false);
  assert.equal(canRetryDelivery({ id: "d1", status: "pending", event: "x" }), false);
  assert.equal(canRetryDelivery({ id: "", status: "failed", event: "x" }), false);
  assert.equal(canRetryDelivery(null), false);
});

test("retryButtonLabel: idle vs in-flight", () => {
  assert.equal(retryButtonLabel(false), "Retry");
  assert.equal(retryButtonLabel(true), "Retrying...");
});

test("retryAriaLabel: names the event, falls back", () => {
  assert.equal(retryAriaLabel("classify.completed"), "Retry failed delivery for classify.completed");
  assert.equal(retryAriaLabel("  "), "Retry failed delivery for event");
});

test("retryToast: success names event", () => {
  const t = retryToast(true, "classify.completed");
  assert.equal(t.kind, "success");
  assert.match(t.text, /Re-fired classify\.completed/);
});

test("retryToast: error surfaces trimmed server message", () => {
  const t = retryToast(false, "x", "  Endpoint disabled  ");
  assert.equal(t.kind, "error");
  assert.equal(t.text, "Endpoint disabled");
  assert.equal(retryToast(false, "x").text, "Retry failed.");
});
