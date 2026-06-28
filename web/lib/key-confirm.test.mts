// Pure tests for the /keys destructive-action confirmation state machine
// (F136). No DOM -- the two-step arm/fire logic is fully decidable here.
import test from "node:test";
import assert from "node:assert/strict";

import {
  armConfirm,
  isArmed,
  rowIsArmed,
  confirmLabel,
  confirmPrompt,
  nextOnTrigger,
} from "./key-confirm.ts";

test("armConfirm builds a pending of the right shape", () => {
  assert.deepEqual(armConfirm("rotate", "k1"), { action: "rotate", id: "k1" });
  assert.deepEqual(armConfirm("revoke", "k2"), { action: "revoke", id: "k2" });
});

test("isArmed matches only the exact action+id", () => {
  const p = armConfirm("revoke", "k1");
  assert.equal(isArmed(p, "revoke", "k1"), true);
  assert.equal(isArmed(p, "rotate", "k1"), false);
  assert.equal(isArmed(p, "revoke", "k2"), false);
  assert.equal(isArmed(null, "revoke", "k1"), false);
});

test("rowIsArmed is true for either action on the id", () => {
  assert.equal(rowIsArmed(armConfirm("rotate", "k1"), "k1"), true);
  assert.equal(rowIsArmed(armConfirm("revoke", "k1"), "k1"), true);
  assert.equal(rowIsArmed(armConfirm("revoke", "k1"), "k2"), false);
  assert.equal(rowIsArmed(null, "k1"), false);
});

test("confirmLabel shows the verb unarmed, Confirm when armed", () => {
  assert.equal(confirmLabel("rotate", false), "Rotate");
  assert.equal(confirmLabel("revoke", false), "Revoke");
  assert.equal(confirmLabel("rotate", true), "Confirm");
  assert.equal(confirmLabel("revoke", true), "Confirm");
});

test("confirmPrompt names the consequence per action", () => {
  assert.match(confirmPrompt("rotate"), /secret stops working/i);
  assert.match(confirmPrompt("revoke"), /start failing/i);
});

test("nextOnTrigger first click arms, no fire", () => {
  const r = nextOnTrigger(null, "revoke", "k1");
  assert.equal(r.fire, false);
  assert.deepEqual(r.pending, { action: "revoke", id: "k1" });
});

test("nextOnTrigger second click on same button fires + clears", () => {
  const armed = armConfirm("revoke", "k1");
  const r = nextOnTrigger(armed, "revoke", "k1");
  assert.equal(r.fire, true);
  assert.equal(r.pending, null);
});

test("nextOnTrigger different row re-arms the new one (no fire)", () => {
  const armed = armConfirm("revoke", "k1");
  const r = nextOnTrigger(armed, "revoke", "k2");
  assert.equal(r.fire, false);
  assert.deepEqual(r.pending, { action: "revoke", id: "k2" });
});

test("nextOnTrigger switching action on same id re-arms (no accidental fire)", () => {
  const armed = armConfirm("rotate", "k1");
  const r = nextOnTrigger(armed, "revoke", "k1");
  assert.equal(r.fire, false);
  assert.deepEqual(r.pending, { action: "revoke", id: "k1" });
});

test("nextOnTrigger is idempotent: re-arm then fire", () => {
  let p = nextOnTrigger(null, "rotate", "k9").pending;
  const r = nextOnTrigger(p, "rotate", "k9");
  assert.equal(r.fire, true);
  assert.equal(r.pending, null);
});
