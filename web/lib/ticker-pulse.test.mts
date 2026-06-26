// Pure tests for the live-ticker increase detector (F76). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { didIncrease, increasedKeys } from "./ticker-pulse.ts";

test("didIncrease: true only on a strict increase", () => {
  assert.equal(didIncrease(3, 5), true);
  assert.equal(didIncrease(0, 1), true);
});

test("didIncrease: false on equal or decrease", () => {
  assert.equal(didIncrease(5, 5), false);
  assert.equal(didIncrease(5, 4), false);
  assert.equal(didIncrease(10, 0), false);
});

test("didIncrease: a first observation never pulses", () => {
  assert.equal(didIncrease(undefined, 7), false);
  assert.equal(didIncrease(null, 7), false);
});

test("didIncrease: non-finite inputs never pulse", () => {
  assert.equal(didIncrease(NaN, 5), false);
  assert.equal(didIncrease(3, NaN), false);
  assert.equal(didIncrease(Infinity, 5), false);
  // A non-finite NEXT is rejected too -- a malformed payload can't flicker.
  assert.equal(didIncrease(3, Infinity), false);
});

test("increasedKeys: returns only the keys that ticked up", () => {
  const prev = { receipt: 4, meme: 10, code: 2 };
  const next = { receipt: 6, meme: 10, code: 1 };
  assert.deepEqual(increasedKeys(prev, next), ["receipt"]);
});

test("increasedKeys: keys absent from prev are first-observations, no pulse", () => {
  const prev = { receipt: 4 };
  const next = { receipt: 4, meme: 3 };
  // `meme` is brand new -- a first observation, so it must NOT pulse.
  assert.deepEqual(increasedKeys(prev, next), []);
});

test("increasedKeys: a null prev (initial mount) pulses nothing", () => {
  assert.deepEqual(increasedKeys(null, { receipt: 9, meme: 2 }), []);
  assert.deepEqual(increasedKeys(undefined, { receipt: 9 }), []);
});

test("increasedKeys: multiple increases all reported, order follows next-keys", () => {
  const prev = { a: 1, b: 1, c: 1 };
  const next = { a: 2, b: 1, c: 5 };
  assert.deepEqual(increasedKeys(prev, next), ["a", "c"]);
});

test("increasedKeys: a count dropping to zero never pulses", () => {
  assert.deepEqual(increasedKeys({ a: 3 }, { a: 0 }), []);
});
