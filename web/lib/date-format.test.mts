// Pure tests for the cross-page date-format helper (F154). No DOM. We assert
// the parse/guard contract and the sortable isoDay shape; the locale string is
// the runtime's job so we only check it is non-empty + not the placeholder.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseInstant,
  shortDate,
  shortDateTime,
  isoDay,
  isValidInstant,
  NO_DATE,
} from "./date-format.ts";

test("parseInstant: ISO string and epoch ms both parse", () => {
  assert.equal(parseInstant("2026-06-28T21:05:00Z"), Date.parse("2026-06-28T21:05:00Z"));
  assert.equal(parseInstant(1_700_000_000_000), 1_700_000_000_000);
});

test("parseInstant: empty / non-finite / garbage collapse to null", () => {
  assert.equal(parseInstant(""), null);
  assert.equal(parseInstant("   "), null);
  assert.equal(parseInstant("not a date"), null);
  assert.equal(parseInstant(NaN), null);
  assert.equal(parseInstant(null), null);
  assert.equal(parseInstant(undefined), null);
});

test("shortDate: bad input is the em-dash placeholder, good input is not", () => {
  assert.equal(shortDate("nope"), NO_DATE);
  assert.equal(shortDate(null), NO_DATE);
  const out = shortDate("2026-06-28T21:05:00Z");
  assert.notEqual(out, NO_DATE);
  assert.ok(out.length > 0);
});

test("shortDateTime: bad input is the em-dash placeholder, good input is not", () => {
  assert.equal(shortDateTime(""), NO_DATE);
  const out = shortDateTime(1_700_000_000_000);
  assert.notEqual(out, NO_DATE);
  assert.ok(out.length > 0);
});

test("isoDay: stable sortable yyyy-mm-dd, UTC", () => {
  assert.equal(isoDay("2026-06-28T21:05:00Z"), "2026-06-28");
  assert.equal(isoDay(Date.parse("2026-01-02T00:00:00Z")), "2026-01-02");
});

test("isoDay: bad input yields empty string so a key-builder no-ops", () => {
  assert.equal(isoDay("garbage"), "");
  assert.equal(isoDay(null), "");
});

test("isValidInstant: mirrors parseInstant", () => {
  assert.equal(isValidInstant("2026-06-28"), true);
  assert.equal(isValidInstant("not real"), false);
  assert.equal(isValidInstant(undefined), false);
});
