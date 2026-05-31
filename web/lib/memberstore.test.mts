// Run with: npm test (uses node --test --import tsx). Mirrors keystore.test.mts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";

import {
  upsertMemberAt,
  listMembersAt,
  removeMemberAt,
  createInvitationAt,
  acceptInvitationAt,
  listInvitationsAt,
  revokeInvitationAt,
  countAdmins,
} from "./memberstore-core";

import { randomUUID } from "node:crypto";

async function tmpStore() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "shotclassify-members-"));
  return { file: path.join(dir, `${randomUUID()}.json`), dir };
}

test("upsertMember creates and updates by lower-cased email", async () => {
  const { file, dir } = await tmpStore();
  try {
    await upsertMemberAt(file, { email: "Alice@Example.com", role: "viewer" });
    let members = await listMembersAt(file);
    assert.equal(members.length, 1);
    assert.equal(members[0].email, "alice@example.com");
    assert.equal(members[0].role, "viewer");

    await upsertMemberAt(file, { email: "alice@example.com", role: "admin" });
    members = await listMembersAt(file);
    assert.equal(members.length, 1, "second upsert must not duplicate");
    assert.equal(members[0].role, "admin");
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("countAdmins excludes the given email", async () => {
  const { file, dir } = await tmpStore();
  try {
    await upsertMemberAt(file, { email: "a@x.com", role: "admin" });
    await upsertMemberAt(file, { email: "b@x.com", role: "admin" });
    await upsertMemberAt(file, { email: "c@x.com", role: "viewer" });
    const members = await listMembersAt(file);
    assert.equal(countAdmins(members), 2);
    assert.equal(countAdmins(members, "a@x.com"), 1);
    assert.equal(countAdmins(members, "c@x.com"), 2);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("invitation accept is single-use and creates the membership", async () => {
  const { file, dir } = await tmpStore();
  try {
    const { token } = await createInvitationAt(file, {
      email: "new@example.com",
      role: "operator",
      invited_by: "owner@example.com",
    });

    const first = await acceptInvitationAt(file, token, "new@example.com");
    assert.ok(first, "first accept must succeed");
    assert.equal(first!.member.role, "operator");
    assert.equal(first!.invitation.status, "accepted");

    const replay = await acceptInvitationAt(file, token, "attacker@example.com");
    assert.equal(replay, null, "replay must fail");

    // Pending list excludes accepted invites by default.
    const pending = await listInvitationsAt(file);
    assert.equal(pending.length, 0);
    const all = await listInvitationsAt(file, { includeInactive: true });
    assert.equal(all.length, 1);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("revoked invitations cannot be accepted", async () => {
  const { file, dir } = await tmpStore();
  try {
    const { invitation, token } = await createInvitationAt(file, {
      email: "x@y.com",
      role: "viewer",
    });
    const revoked = await revokeInvitationAt(file, invitation.id);
    assert.equal(revoked!.status, "revoked");
    const result = await acceptInvitationAt(file, token, "x@y.com");
    assert.equal(result, null);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("removeMember deletes a member and returns false for unknown emails", async () => {
  const { file, dir } = await tmpStore();
  try {
    await upsertMemberAt(file, { email: "gone@x.com", role: "viewer" });
    const before = await listMembersAt(file);
    assert.equal(before.length, 1, `expected 1 member before remove, got ${JSON.stringify(before)}`);
    assert.equal(await removeMemberAt(file, "GONE@x.com"), true);
    assert.equal(await removeMemberAt(file, "gone@x.com"), false);
    const members = await listMembersAt(file);
    assert.equal(members.length, 0, `expected 0 after remove, got ${JSON.stringify(members)}`);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});
