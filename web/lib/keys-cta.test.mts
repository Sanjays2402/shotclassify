// Pure tests for the /keys create-form CTA helper (F148). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  KEY_NAME_INPUT_ID,
  createFormScrollOptions,
  scrollToCreateForm,
} from "./keys-cta.ts";

test("KEY_NAME_INPUT_ID matches the create form's name input", () => {
  assert.equal(KEY_NAME_INPUT_ID, "key-name");
});

test("createFormScrollOptions: smooth by default, instant for reduced motion", () => {
  assert.deepEqual(createFormScrollOptions(), { behavior: "smooth", block: "start" });
  assert.deepEqual(createFormScrollOptions(false), { behavior: "smooth", block: "start" });
  assert.deepEqual(createFormScrollOptions(true), { behavior: "auto", block: "start" });
});

test("scrollToCreateForm: scrolls then focuses the resolved input", () => {
  const calls: string[] = [];
  const el = {
    scrollIntoView: (o: ScrollIntoViewOptions) => calls.push(`scroll:${o.behavior}`),
    focus: () => calls.push("focus"),
  };
  const ok = scrollToCreateForm((id) => (id === "key-name" ? el : null));
  assert.equal(ok, true);
  assert.deepEqual(calls, ["scroll:smooth", "focus"]);
});

test("scrollToCreateForm: returns false when the input is absent", () => {
  let touched = false;
  const ok = scrollToCreateForm(() => {
    touched = true;
    return null;
  });
  assert.equal(ok, false);
  assert.equal(touched, true);
});
