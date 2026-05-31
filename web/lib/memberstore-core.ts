// Team membership and email invitation store, JSON-file backed to match
// the existing `keystore-core` pattern in this app. Pure module: no Next or
// `server-only` imports so tests can drive it without spinning up Next.js.
//
// Why JSON files: the rest of the web app uses the same lightweight store
// pattern (api_keys.json, webhooks.json) so we stay consistent and avoid
// dragging in a new database for a single feature.

import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export type Role = "admin" | "operator" | "viewer";

export const ALL_ROLES: Role[] = ["admin", "operator", "viewer"];

export function isRole(value: unknown): value is Role {
  return value === "admin" || value === "operator" || value === "viewer";
}

export type Member = {
  id: string;
  email: string;
  role: Role;
  invited_by: string | null;
  created_at: string;
  updated_at: string;
};

export type Invitation = {
  id: string;
  email: string;
  role: Role;
  token_hash: string;
  invited_by: string | null;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  accepted_by: string | null;
  revoked_at: string | null;
};

export type InvitationView = Omit<Invitation, "token_hash"> & {
  status: "pending" | "expired" | "revoked" | "accepted";
};

type Store = {
  members: Member[];
  invitations: Invitation[];
};

const EMPTY = (): Store => ({ members: [], invitations: [] });

export function defaultMembersStorePath(): string {
  return (
    process.env.SHOTCLASSIFY_MEMBERS_FILE ||
    path.join(process.cwd(), "..", "storage", "members.json")
  );
}

function newId(): string {
  return crypto.randomBytes(8).toString("hex");
}

function newToken(): string {
  // `inv_` + 32 url-safe random bytes; mirrors the FastAPI side.
  const raw = crypto.randomBytes(32).toString("base64url");
  return `inv_${raw}`;
}

function hashToken(token: string): string {
  return crypto.createHash("sha256").update(token).digest("hex");
}

function normalizeEmail(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const trimmed = raw.trim().toLowerCase();
  if (!trimmed || !trimmed.includes("@") || trimmed.length > 255) return "";
  return trimmed;
}

async function readStore(file: string): Promise<Store> {
  try {
    const raw = await fs.readFile(file, "utf8");
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return EMPTY();
    return {
      members: Array.isArray(parsed.members) ? parsed.members : [],
      invitations: Array.isArray(parsed.invitations) ? parsed.invitations : [],
    };
  } catch (err: any) {
    if (err?.code === "ENOENT") return EMPTY();
    throw err;
  }
}

async function writeStore(file: string, store: Store): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  // Atomic write: tmp file then rename so a crash mid-write cannot truncate
  // the store and lock the workspace out of role management.
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(store, null, 2), { mode: 0o600 });
  await fs.rename(tmp, file);
}

function toInvitationView(inv: Invitation): InvitationView {
  let status: InvitationView["status"];
  if (inv.revoked_at) status = "revoked";
  else if (inv.accepted_at) status = "accepted";
  else if (new Date(inv.expires_at).getTime() < Date.now()) status = "expired";
  else status = "pending";
  const { token_hash: _hash, ...rest } = inv;
  return { ...rest, status };
}

// ----------------------------------------------------------------- members

export async function listMembersAt(file: string): Promise<Member[]> {
  const store = await readStore(file);
  return [...store.members].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
}

export async function upsertMemberAt(
  file: string,
  input: { email: string; role: Role; invited_by?: string | null },
): Promise<Member> {
  const email = normalizeEmail(input.email);
  if (!email) throw new Error("A valid email address is required.");
  if (!isRole(input.role)) throw new Error("Invalid role.");
  const store = await readStore(file);
  const now = new Date().toISOString();
  const existing = store.members.find((m) => m.email === email);
  if (existing) {
    existing.role = input.role;
    existing.updated_at = now;
    await writeStore(file, store);
    return existing;
  }
  const member: Member = {
    id: newId(),
    email,
    role: input.role,
    invited_by: input.invited_by ?? null,
    created_at: now,
    updated_at: now,
  };
  store.members.push(member);
  await writeStore(file, store);
  return member;
}

export async function removeMemberAt(
  file: string,
  email: string,
): Promise<boolean> {
  const lower = normalizeEmail(email);
  if (!lower) return false;
  const store = await readStore(file);
  const before = store.members.length;
  store.members = store.members.filter((m) => m.email !== lower);
  if (store.members.length === before) return false;
  await writeStore(file, store);
  return true;
}

export function countAdmins(members: Member[], excludeEmail?: string): number {
  const skip = excludeEmail ? normalizeEmail(excludeEmail) : "";
  return members.filter((m) => m.role === "admin" && m.email !== skip).length;
}

// ------------------------------------------------------------- invitations

export async function listInvitationsAt(
  file: string,
  { includeInactive = false }: { includeInactive?: boolean } = {},
): Promise<InvitationView[]> {
  const store = await readStore(file);
  const views = store.invitations
    .slice()
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map(toInvitationView);
  return includeInactive ? views : views.filter((v) => v.status === "pending");
}

export type CreatedInvitation = {
  invitation: InvitationView;
  token: string;
};

export async function createInvitationAt(
  file: string,
  input: {
    email: string;
    role: Role;
    invited_by?: string | null;
    ttl_days?: number;
  },
): Promise<CreatedInvitation> {
  const email = normalizeEmail(input.email);
  if (!email) throw new Error("A valid email address is required.");
  if (!isRole(input.role)) throw new Error("Invalid role.");
  const ttl = Math.min(90, Math.max(1, Math.floor(input.ttl_days ?? 7)));
  const token = newToken();
  const now = new Date();
  const inv: Invitation = {
    id: newId(),
    email,
    role: input.role,
    token_hash: hashToken(token),
    invited_by: input.invited_by ?? null,
    created_at: now.toISOString(),
    expires_at: new Date(now.getTime() + ttl * 86_400_000).toISOString(),
    accepted_at: null,
    accepted_by: null,
    revoked_at: null,
  };
  const store = await readStore(file);
  store.invitations.push(inv);
  await writeStore(file, store);
  return { invitation: toInvitationView(inv), token };
}

export async function revokeInvitationAt(
  file: string,
  id: string,
): Promise<InvitationView | null> {
  const store = await readStore(file);
  const inv = store.invitations.find((i) => i.id === id);
  if (!inv) return null;
  if (!inv.revoked_at && !inv.accepted_at) {
    inv.revoked_at = new Date().toISOString();
    await writeStore(file, store);
  }
  return toInvitationView(inv);
}

export async function acceptInvitationAt(
  file: string,
  token: string,
  acceptingEmail: string,
): Promise<{ invitation: InvitationView; member: Member } | null> {
  if (!token) return null;
  const email = normalizeEmail(acceptingEmail);
  if (!email) return null;
  const store = await readStore(file);
  const inv = store.invitations.find((i) => i.token_hash === hashToken(token));
  if (!inv) return null;
  if (inv.revoked_at || inv.accepted_at) return null;
  if (new Date(inv.expires_at).getTime() < Date.now()) return null;
  const now = new Date().toISOString();
  inv.accepted_at = now;
  inv.accepted_by = email;
  const existing = store.members.find((m) => m.email === email);
  let member: Member;
  if (existing) {
    existing.role = inv.role;
    existing.updated_at = now;
    member = existing;
  } else {
    member = {
      id: newId(),
      email,
      role: inv.role,
      invited_by: inv.invited_by,
      created_at: now,
      updated_at: now,
    };
    store.members.push(member);
  }
  await writeStore(file, store);
  return { invitation: toInvitationView(inv), member };
}

export async function roleForMemberAt(
  file: string,
  email: string,
): Promise<Role | null> {
  const lower = normalizeEmail(email);
  if (!lower) return null;
  const store = await readStore(file);
  const found = store.members.find((m) => m.email === lower);
  return found?.role ?? null;
}
