import { test } from "node:test";
import assert from "node:assert/strict";
import { filterShotListQuery, isValidShotId } from "./v1-core";

test("filterShotListQuery drops unknown params and defaults limit", () => {
  const q = new URLSearchParams("category=cover_drive&secret=hax&offset=10");
  const r = filterShotListQuery(q);
  assert.equal(r.ok, true);
  if (!r.ok) return;
  assert.equal(r.params.get("category"), "cover_drive");
  assert.equal(r.params.get("offset"), "10");
  assert.equal(r.params.get("secret"), null);
  assert.equal(r.params.get("limit"), "50");
});

test("filterShotListQuery caps limit at 200", () => {
  const q = new URLSearchParams("limit=999");
  const r = filterShotListQuery(q);
  assert.equal(r.ok, true);
  if (!r.ok) return;
  assert.equal(r.params.get("limit"), "200");
});

test("filterShotListQuery floors fractional limits", () => {
  const q = new URLSearchParams("limit=12.7");
  const r = filterShotListQuery(q);
  assert.equal(r.ok, true);
  if (!r.ok) return;
  assert.equal(r.params.get("limit"), "12");
});

test("filterShotListQuery rejects non-positive or non-numeric limit", () => {
  for (const bad of ["0", "-5", "abc"]) {
    const r = filterShotListQuery(new URLSearchParams(`limit=${bad}`));
    assert.equal(r.ok, false);
    if (r.ok) return;
    assert.equal(r.code, "invalid_limit");
  }
});

test("isValidShotId accepts safe ids and rejects bad ones", () => {
  assert.equal(isValidShotId("sh_01HXYZ"), true);
  assert.equal(isValidShotId("abc-123_DEF"), true);
  assert.equal(isValidShotId(""), false);
  assert.equal(isValidShotId("../etc/passwd"), false);
  assert.equal(isValidShotId("has space"), false);
  assert.equal(isValidShotId("a".repeat(65)), false);
});
