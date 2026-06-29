// Pure tests for the /shots filter Escape behaviour (F145). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { isBareEscape, filterEscapeAction } from "./filter-esc.ts";

test("isBareEscape: bare Escape (and legacy Esc) is ours", () => {
  assert.equal(isBareEscape({ key: "Escape" }), true);
  assert.equal(isBareEscape({ key: "Esc" }), true);
});

test("isBareEscape: modified Escape / other keys are not", () => {
  assert.equal(isBareEscape({ key: "Escape", metaKey: true }), false);
  assert.equal(isBareEscape({ key: "Escape", ctrlKey: true }), false);
  assert.equal(isBareEscape({ key: "Escape", altKey: true }), false);
  assert.equal(isBareEscape({ key: "Enter" }), false);
});

test("filterEscapeAction: clears a non-empty control first, then leaves", () => {
  assert.equal(filterEscapeAction({ key: "Escape" }, true), "clear");
  assert.equal(filterEscapeAction({ key: "Escape" }, false), "leave");
});

test("filterEscapeAction: non-escape is a no-op", () => {
  assert.equal(filterEscapeAction({ key: "x" }, true), "none");
  assert.equal(filterEscapeAction({ key: "Escape", metaKey: true }, false), "none");
});
