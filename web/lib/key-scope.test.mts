// Pure tests for the /keys scope model (F130). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  SCOPE_OPTIONS,
  scopesForSelection,
  scopeTier,
  scopeLabel,
  scopeDescription,
  scopeCanWrite,
  type KeyScope,
} from "./key-scope.ts";

test("scopesForSelection: each tier expands with the implied hierarchy", () => {
  assert.deepEqual(scopesForSelection("read"), ["read"]);
  assert.deepEqual(scopesForSelection("write"), ["read", "write"]);
  assert.deepEqual(scopesForSelection("admin"), ["read", "write", "admin"]);
});

test("scopesForSelection: an unknown value coerces to the read+write default", () => {
  assert.deepEqual(scopesForSelection("nonsense"), ["read", "write"]);
  assert.deepEqual(scopesForSelection("" as KeyScope), ["read", "write"]);
});

test("scopeTier: admin wins over write wins over read", () => {
  assert.equal(scopeTier(["read", "write", "admin"]), "admin");
  assert.equal(scopeTier(["read", "write"]), "write");
  assert.equal(scopeTier(["read"]), "read");
  // Order in the array doesn't matter -- the highest present tier wins.
  assert.equal(scopeTier(["admin", "read"]), "admin");
});

test("scopeTier: missing / empty scopes fall back to the read+write default", () => {
  assert.equal(scopeTier(undefined), "write");
  assert.equal(scopeTier(null), "write");
  assert.equal(scopeTier([]), "write");
});

test("scopeLabel: short badge words per tier", () => {
  assert.equal(scopeLabel(["read", "write", "admin"]), "admin");
  assert.equal(scopeLabel(["read", "write"]), "read+write");
  assert.equal(scopeLabel(["read"]), "read");
  assert.equal(scopeLabel(undefined), "read+write");
});

test("scopeDescription: a sentence per tier, default for legacy", () => {
  assert.match(scopeDescription(["read"]), /403 insufficient_scope/);
  assert.match(scopeDescription(["read", "write"]), /POST \/v1\/classify/);
  assert.match(scopeDescription(["read", "write", "admin"]), /Admin scope/);
  // Legacy (undefined) keys read as the read+write default.
  assert.match(scopeDescription(undefined), /POST \/v1\/classify/);
});

test("scopeCanWrite: only write + admin tiers can write", () => {
  assert.equal(scopeCanWrite(["read", "write"]), true);
  assert.equal(scopeCanWrite(["read", "write", "admin"]), true);
  assert.equal(scopeCanWrite(["read"]), false);
  // Legacy default is read+write -> write-capable.
  assert.equal(scopeCanWrite(undefined), true);
});

test("SCOPE_OPTIONS: every option round-trips through scopesForSelection -> scopeTier", () => {
  // Picking any option and expanding it must reduce back to the same tier, so
  // the create form and the list badge agree on what a fresh key is.
  for (const opt of SCOPE_OPTIONS) {
    const expanded = scopesForSelection(opt.value);
    assert.equal(scopeTier(expanded), opt.value, `tier round-trip for ${opt.value}`);
    assert.equal(scopeLabel(expanded), opt.summary, `label for ${opt.value}`);
  }
});

test("SCOPE_OPTIONS: the catalogue is the three known tiers, write first", () => {
  assert.deepEqual(
    SCOPE_OPTIONS.map((o) => o.value),
    ["write", "read", "admin"],
  );
});
