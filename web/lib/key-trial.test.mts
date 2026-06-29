// Pure tests for the /keys/[id] try-it trial-state copy (F155). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { KEYS_CREATE_HREF, keyTrialState } from "./key-trial.ts";

test("KEYS_CREATE_HREF anchors back to the create form", () => {
  assert.equal(KEYS_CREATE_HREF, "/keys#key-name");
});

test("keyTrialState: revealed -> full secret, no hint or CTA", () => {
  const s = keyTrialState(true);
  assert.equal(s.revealed, true);
  assert.equal(s.hint, "");
  assert.equal(s.cta, null);
});

test("keyTrialState: hidden -> prefix hint + generate CTA", () => {
  const s = keyTrialState(false);
  assert.equal(s.revealed, false);
  assert.equal(s.cta, "Generate one above");
  assert.match(s.hint, /hashed at rest/);
});
