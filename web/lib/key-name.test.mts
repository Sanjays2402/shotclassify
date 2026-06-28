// Pure tests for the /keys name validator (F132). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  validateKeyName,
  canSubmitKeyName,
  KEY_NAME_MAX,
} from "./key-name.ts";

test("validateKeyName: a clean unique name is ok and trimmed", () => {
  const v = validateKeyName("  production  ", ["ci", "dev"]);
  assert.equal(v.ok, true);
  assert.equal(v.kind, "ok");
  assert.equal(v.normalized, "production");
  assert.equal(v.message, "");
});

test("validateKeyName: blank / whitespace-only is empty with a hint", () => {
  for (const raw of ["", "   ", "\t\n"]) {
    const v = validateKeyName(raw, []);
    assert.equal(v.ok, false);
    assert.equal(v.kind, "empty");
    assert.equal(v.normalized, "");
    assert.match(v.message, /name/i);
  }
});

test("validateKeyName: a non-string name is treated as empty", () => {
  const v = validateKeyName(undefined, []);
  assert.equal(v.ok, false);
  assert.equal(v.kind, "empty");
});

test("validateKeyName: over the cap is rejected with the live count", () => {
  const long = "x".repeat(KEY_NAME_MAX + 5);
  const v = validateKeyName(long, []);
  assert.equal(v.ok, false);
  assert.equal(v.kind, "too-long");
  assert.match(v.message, new RegExp(String(KEY_NAME_MAX)));
  assert.match(v.message, new RegExp(String(KEY_NAME_MAX + 5)));
});

test("validateKeyName: exactly at the cap is allowed", () => {
  const v = validateKeyName("y".repeat(KEY_NAME_MAX), []);
  assert.equal(v.ok, true);
});

test("validateKeyName: duplicate detection is case- and whitespace-insensitive", () => {
  assert.equal(validateKeyName("CI", ["ci"]).kind, "duplicate");
  assert.equal(validateKeyName("  ci ", ["CI"]).kind, "duplicate");
  assert.equal(validateKeyName("prod", ["ci", "dev"]).ok, true);
});

test("validateKeyName: a non-array existing list is treated as none taken", () => {
  // @ts-expect-error -- deliberately passing the wrong type to prove it no-ops.
  assert.equal(validateKeyName("ci", null).ok, true);
});

test("validateKeyName: existing entries that aren't strings are ignored", () => {
  // @ts-expect-error -- a malformed list shouldn't throw.
  const v = validateKeyName("ci", [null, 42, "dev"]);
  assert.equal(v.ok, true);
});

test("canSubmitKeyName: mirrors validateKeyName().ok", () => {
  assert.equal(canSubmitKeyName("ci", ["dev"]), true);
  assert.equal(canSubmitKeyName("", []), false);
  assert.equal(canSubmitKeyName("dev", ["dev"]), false);
});
