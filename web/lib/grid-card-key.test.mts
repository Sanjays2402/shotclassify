// Pure tests for the ShotGrid card keyboard-open helper (F150). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { shouldOpenCard, shotDetailHref } from "./grid-card-key.ts";

test("shouldOpenCard: Enter on the card itself opens", () => {
  assert.equal(shouldOpenCard({ key: "Enter", selfTarget: true }), true);
});

test("shouldOpenCard: Space variants on the card open (matches a button)", () => {
  assert.equal(shouldOpenCard({ key: " ", selfTarget: true }), true);
  assert.equal(shouldOpenCard({ key: "Spacebar", selfTarget: true }), true);
});

test("shouldOpenCard: inner-control events never open the card", () => {
  assert.equal(shouldOpenCard({ key: "Enter", selfTarget: false }), false);
  assert.equal(shouldOpenCard({ key: " ", selfTarget: false }), false);
});

test("shouldOpenCard: other keys never open", () => {
  assert.equal(shouldOpenCard({ key: "a", selfTarget: true }), false);
  assert.equal(shouldOpenCard({ key: "Tab", selfTarget: true }), false);
  assert.equal(shouldOpenCard({ key: "ArrowDown", selfTarget: true }), false);
});

test("shotDetailHref: builds the detail path, blanks an empty id", () => {
  assert.equal(shotDetailHref("abc123"), "/shots/abc123");
  assert.equal(shotDetailHref("  x9  "), "/shots/x9");
  assert.equal(shotDetailHref(""), "");
  assert.equal(shotDetailHref("   "), "");
  assert.equal(shotDetailHref(null), "");
  assert.equal(shotDetailHref(undefined), "");
});
