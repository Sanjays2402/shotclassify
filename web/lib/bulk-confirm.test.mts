// Pure tests for the bulk-action two-step confirm helper (F149). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  bulkIsArmed,
  bulkConfirmLabel,
  bulkConfirmPrompt,
  bulkNextOnTrigger,
} from "./bulk-confirm.ts";

test("bulkIsArmed: only the matching action reads armed", () => {
  assert.equal(bulkIsArmed("mark_all_read", "mark_all_read"), true);
  assert.equal(bulkIsArmed("mark_all_read", "clear_all"), false);
  assert.equal(bulkIsArmed(null, "mark_all_read"), false);
});

test("bulkConfirmLabel: verb at rest, Confirm when armed", () => {
  assert.equal(bulkConfirmLabel("mark_all_read", false), "Mark all read");
  assert.equal(bulkConfirmLabel("mark_all_read", true), "Confirm");
  assert.equal(bulkConfirmLabel("clear_all", false), "Clear all");
  assert.equal(bulkConfirmLabel("clear_all", true), "Confirm");
});

test("bulkConfirmPrompt: names the consequence per action", () => {
  assert.match(bulkConfirmPrompt("mark_all_read"), /read/);
  assert.match(bulkConfirmPrompt("clear_all"), /cannot be undone/);
});

test("bulkNextOnTrigger: first click arms, second fires", () => {
  const armed = bulkNextOnTrigger(null, "mark_all_read");
  assert.deepEqual(armed, { fire: false, pending: "mark_all_read" });
  const fired = bulkNextOnTrigger(armed.pending, "mark_all_read");
  assert.deepEqual(fired, { fire: true, pending: null });
});

test("bulkNextOnTrigger: arming a different action replaces, never double-fires", () => {
  const r = bulkNextOnTrigger("mark_all_read", "clear_all");
  assert.deepEqual(r, { fire: false, pending: "clear_all" });
});
