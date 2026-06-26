// Pure tests for the relative-time formatter (F59). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { relativeTime, relativeTimeFromNow } from "./relative-time.ts";

const NOW = 1_700_000_000_000; // a fixed reference instant
const SEC = 1000;
const MIN = 60 * SEC;
const HR = 60 * MIN;
const DAY = 24 * HR;

test("relativeTime: sub-45s gaps and the exact instant read 'just now'", () => {
  assert.equal(relativeTime(NOW, NOW), "just now");
  assert.equal(relativeTime(NOW - 10 * SEC, NOW), "just now");
  assert.equal(relativeTime(NOW - 44 * SEC, NOW), "just now");
});

test("relativeTime: a future timestamp never reads 'in ...'", () => {
  assert.equal(relativeTime(NOW + 5 * SEC, NOW), "just now");
  assert.equal(relativeTime(NOW + 10 * DAY, NOW), "just now");
});

test("relativeTime: minutes", () => {
  assert.equal(relativeTime(NOW - 46 * SEC, NOW), "1m ago");
  assert.equal(relativeTime(NOW - 3 * MIN, NOW), "3m ago");
  assert.equal(relativeTime(NOW - 59 * MIN, NOW), "59m ago");
});

test("relativeTime: hours", () => {
  assert.equal(relativeTime(NOW - 1 * HR, NOW), "1h ago");
  assert.equal(relativeTime(NOW - 5 * HR, NOW), "5h ago");
  assert.equal(relativeTime(NOW - 23 * HR, NOW), "23h ago");
});

test("relativeTime: days", () => {
  assert.equal(relativeTime(NOW - 1 * DAY, NOW), "1d ago");
  assert.equal(relativeTime(NOW - 6 * DAY, NOW), "6d ago");
});

test("relativeTime: weeks, then a coarse 30d+ cap", () => {
  assert.equal(relativeTime(NOW - 7 * DAY, NOW), "1w ago");
  assert.equal(relativeTime(NOW - 21 * DAY, NOW), "3w ago");
  assert.equal(relativeTime(NOW - 60 * DAY, NOW), "30d+ ago");
});

test("relativeTime: non-finite inputs degrade to an empty string", () => {
  assert.equal(relativeTime(NaN, NOW), "");
  assert.equal(relativeTime(NOW, NaN), "");
  assert.equal(relativeTime(Infinity, NOW), "");
});

test("relativeTimeFromNow: defaults now to the wall clock", () => {
  // A timestamp a couple minutes back should read in minutes regardless of
  // the actual wall clock.
  assert.equal(relativeTimeFromNow(Date.now() - 2 * MIN), "2m ago");
  assert.equal(relativeTimeFromNow(Date.now()), "just now");
});
