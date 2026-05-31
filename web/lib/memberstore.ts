// Server-only wrapper that pins the members store to a single on-disk file.
// Mirrors `keystore.ts` so the rest of the codebase recognizes the pattern.
import "server-only";
import {
  defaultMembersStorePath,
  listMembersAt,
  upsertMemberAt,
  removeMemberAt,
  listInvitationsAt,
  createInvitationAt,
  revokeInvitationAt,
  acceptInvitationAt,
  countAdmins,
  roleForMemberAt,
  type Member,
  type InvitationView,
  type CreatedInvitation,
  type Role,
} from "./memberstore-core";

export type { Member, InvitationView, CreatedInvitation, Role } from "./memberstore-core";
export { ALL_ROLES, isRole } from "./memberstore-core";

const STORE = defaultMembersStorePath();

export function listMembers(): Promise<Member[]> {
  return listMembersAt(STORE);
}

export function upsertMember(input: {
  email: string;
  role: Role;
  invited_by?: string | null;
}): Promise<Member> {
  return upsertMemberAt(STORE, input);
}

export function removeMember(email: string): Promise<boolean> {
  return removeMemberAt(STORE, email);
}

export function listInvitations(opts?: {
  includeInactive?: boolean;
}): Promise<InvitationView[]> {
  return listInvitationsAt(STORE, opts);
}

export function createInvitation(input: {
  email: string;
  role: Role;
  invited_by?: string | null;
  ttl_days?: number;
}): Promise<CreatedInvitation> {
  return createInvitationAt(STORE, input);
}

export function revokeInvitation(id: string): Promise<InvitationView | null> {
  return revokeInvitationAt(STORE, id);
}

export function acceptInvitation(token: string, acceptingEmail: string) {
  return acceptInvitationAt(STORE, token, acceptingEmail);
}

export function roleForMember(email: string): Promise<Role | null> {
  return roleForMemberAt(STORE, email);
}

export { countAdmins };
