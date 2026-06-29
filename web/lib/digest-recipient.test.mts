// Pure tests for the /digest recipient validation helper (F153). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  isBlankRecipient,
  isValidRecipient,
  canSendDigest,
  recipientHint,
} from "./digest-recipient.ts";

test("isBlankRecipient: empty / whitespace / null are blank", () => {
  assert.equal(isBlankRecipient(""), true);
  assert.equal(isBlankRecipient("   "), true);
  assert.equal(isBlankRecipient(null), true);
  assert.equal(isBlankRecipient("a@b.co"), false);
});

test("isValidRecipient: accepts plain addresses, rejects fumbles", () => {
  assert.equal(isValidRecipient("you@example.com"), true);
  assert.equal(isValidRecipient(" name@sub.example.io "), true);
  assert.equal(isValidRecipient("nope"), false);
  assert.equal(isValidRecipient("a@b"), false);
  assert.equal(isValidRecipient("a b@c.com"), false);
  assert.equal(isValidRecipient("a@@b.com"), false);
  assert.equal(isValidRecipient("a@b..com"), false);
  assert.equal(isValidRecipient(""), false);
});

test("canSendDigest: blank ok, valid ok, malformed blocked, busy blocks", () => {
  assert.equal(canSendDigest("", false), true);
  assert.equal(canSendDigest("you@example.com", false), true);
  assert.equal(canSendDigest("nope", false), false);
  assert.equal(canSendDigest("", true), false);
  assert.equal(canSendDigest("you@example.com", true), false);
});

test("recipientHint: silent when blank/valid, nudges on malformed", () => {
  assert.equal(recipientHint(""), null);
  assert.equal(recipientHint("you@example.com"), null);
  assert.match(recipientHint("nope") ?? "", /single valid email/);
});
