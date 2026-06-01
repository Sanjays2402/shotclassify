// Pure, no `server-only`, no Next deps. Used by `keystore.ts` AND by tests.
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export type KeyScope = "read" | "write" | "admin";

export const ALL_SCOPES: KeyScope[] = ["read", "write", "admin"];

export function normalizeScopes(input: unknown): KeyScope[] {
  if (!Array.isArray(input)) return ["read", "write"];
  const seen = new Set<KeyScope>();
  for (const raw of input) {
    if (raw === "read" || raw === "write" || raw === "admin") seen.add(raw);
  }
  if (seen.size === 0) return ["read", "write"];
  // 'admin' implies 'write' implies 'read'. Enterprise customers expect a
  // strict hierarchy so an admin token never has to be paired with lower
  // scopes to perform mundane reads.
  if (seen.has("admin")) {
    seen.add("write");
  }
  if (seen.has("write")) seen.add("read");
  return ALL_SCOPES.filter((s) => seen.has(s));
}

export function hasScope(key: { scopes?: KeyScope[] }, needed: KeyScope): boolean {
  const scopes = key.scopes ?? ["read", "write"];
  return scopes.includes(needed);
}

export type StoredKey = {
  id: string;
  name: string;
  prefix: string;
  hash: string;
  created_at: string;
  last_used_at: string | null;
  usage_count: number;
  rotated_at?: string | null;
  scopes?: KeyScope[];
  /**
   * Tenant binding for this key. Webhook subscriptions, allowlists, and
   * deliveries are partitioned by this value so two customers sharing the
   * same install never observe each other's integrations. Legacy keys with
   * no workspace are treated as belonging to DEFAULT_WORKSPACE_ID.
   */
  workspace_id?: string;
  /** Per-UTC-day request counts, keyed YYYY-MM-DD. Trimmed to ~90 days. */
  daily_usage?: Record<string, number>;
  /**
   * Per-key source-IP allowlist. Each entry is a bare IPv4/IPv6 address
   * or a CIDR range. When non-empty, the key is only accepted from a
   * request whose client IP matches at least one entry. An empty array
   * (the default for legacy keys) means "accept from any IP", preserving
   * backward compatibility. Stored normalized (lower-case, no leading
   * zeroes, with a network suffix).
   */
  allowed_cidrs?: string[];
};

export const DEFAULT_WORKSPACE_ID = "default";

export function workspaceOf(key: { workspace_id?: string | null }): string {
  const w = (key.workspace_id || "").trim();
  return w || DEFAULT_WORKSPACE_ID;
}

export function normalizeWorkspaceId(input: unknown): string {
  if (typeof input !== "string") return DEFAULT_WORKSPACE_ID;
  const v = input.trim().toLowerCase();
  if (!v) return DEFAULT_WORKSPACE_ID;
  if (!/^[a-z0-9][a-z0-9_\-]{0,62}$/.test(v)) return DEFAULT_WORKSPACE_ID;
  return v;
}

const DAILY_USAGE_RETENTION_DAYS = 90;

function todayKey(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

function trimDailyUsage(
  daily: Record<string, number>,
  now: Date = new Date(),
): Record<string, number> {
  const cutoffMs = now.getTime() - DAILY_USAGE_RETENTION_DAYS * 86_400_000;
  const out: Record<string, number> = {};
  for (const [day, count] of Object.entries(daily)) {
    const t = Date.parse(`${day}T00:00:00Z`);
    if (!Number.isFinite(t)) continue;
    if (t < cutoffMs) continue;
    out[day] = count;
  }
  return out;
}

/**
 * Build a dense last-N-days series ending today (UTC). Missing days are 0.
 * Useful for rendering a sparkline without client-side gap filling.
 */
export function dailyUsageSeries(
  key: { daily_usage?: Record<string, number> },
  days: number,
  now: Date = new Date(),
): { day: string; count: number }[] {
  const out: { day: string; count: number }[] = [];
  const start = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(start.getTime() - i * 86_400_000);
    const key_ = d.toISOString().slice(0, 10);
    out.push({ day: key_, count: key?.daily_usage?.[key_] ?? 0 });
  }
  return out;
}

export type CreatedKey = {
  key: StoredKey;
  plaintext: string;
};

export function defaultStorePath(): string {
  return (
    process.env.SHOTCLASSIFY_KEYS_FILE ||
    path.join(process.cwd(), "..", "storage", "api_keys.json")
  );
}

async function ensureDir(file: string) {
  await fs.mkdir(path.dirname(file), { recursive: true });
}

export async function readAll(file: string): Promise<StoredKey[]> {
  try {
    const raw = await fs.readFile(file, "utf8");
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as StoredKey[];
  } catch (err: any) {
    if (err?.code === "ENOENT") return [];
    throw err;
  }
}

export async function writeAll(
  file: string,
  keys: StoredKey[],
): Promise<void> {
  await ensureDir(file);
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(keys, null, 2), "utf8");
  await fs.rename(tmp, file);
}

export function sha256(s: string): string {
  return crypto.createHash("sha256").update(s).digest("hex");
}

export function newToken(): string {
  return `sk_live_${crypto.randomBytes(24).toString("base64url")}`;
}

export async function listKeysAt(file: string): Promise<StoredKey[]> {
  const all = await readAll(file);
  return all.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export async function createKeyAt(
  file: string,
  name: string,
  scopes?: unknown,
  workspaceId?: unknown,
): Promise<CreatedKey> {
  const cleanName = (name || "").trim().slice(0, 80) || "Untitled key";
  const plaintext = newToken();
  const key: StoredKey = {
    id: crypto.randomUUID(),
    name: cleanName,
    prefix: plaintext.slice(0, 12),
    hash: sha256(plaintext),
    created_at: new Date().toISOString(),
    last_used_at: null,
    usage_count: 0,
    rotated_at: null,
    scopes: normalizeScopes(scopes),
    workspace_id: normalizeWorkspaceId(workspaceId),
  };
  const all = await readAll(file);
  all.push(key);
  await writeAll(file, all);
  return { key, plaintext };
}

export async function rotateKeyAt(
  file: string,
  id: string,
): Promise<CreatedKey | null> {
  const all = await readAll(file);
  const idx = all.findIndex((k) => k.id === id);
  if (idx === -1) return null;
  const plaintext = newToken();
  const existing = all[idx];
  const rotated: StoredKey = {
    ...existing,
    prefix: plaintext.slice(0, 12),
    hash: sha256(plaintext),
    last_used_at: null,
    rotated_at: new Date().toISOString(),
    scopes: existing.scopes && existing.scopes.length > 0 ? existing.scopes : ["read", "write"],
  };
  all[idx] = rotated;
  await writeAll(file, all);
  return { key: rotated, plaintext };
}

export async function deleteKeyAt(file: string, id: string): Promise<boolean> {
  const all = await readAll(file);
  const next = all.filter((k) => k.id !== id);
  if (next.length === all.length) return false;
  await writeAll(file, next);
  return true;
}

export async function verifyAndTouchAt(
  file: string,
  plaintext: string,
): Promise<StoredKey | null> {
  if (!plaintext || !plaintext.startsWith("sk_live_")) return null;
  const hash = sha256(plaintext);
  const all = await readAll(file);
  const match = all.find((k) => k.hash === hash);
  if (!match) return null;
  if (!match.scopes || match.scopes.length === 0) {
    // Backfill legacy keys with full scope set on first verify.
    match.scopes = ["read", "write"];
  }
  const now = new Date();
  match.last_used_at = now.toISOString();
  match.usage_count += 1;
  const day = todayKey(now);
  const daily = match.daily_usage ?? {};
  daily[day] = (daily[day] ?? 0) + 1;
  match.daily_usage = trimDailyUsage(daily, now);
  await writeAll(file, all);
  return match;
}

export async function getKeyAt(
  file: string,
  id: string,
): Promise<StoredKey | null> {
  const all = await readAll(file);
  return all.find((k) => k.id === id) ?? null;
}

export async function renameKeyAt(
  file: string,
  id: string,
  name: string,
): Promise<StoredKey | null> {
  const all = await readAll(file);
  const idx = all.findIndex((k) => k.id === id);
  if (idx === -1) return null;
  const clean = (name || "").trim().slice(0, 80);
  if (!clean) return null;
  all[idx] = { ...all[idx], name: clean };
  await writeAll(file, all);
  return all[idx];
}

export async function setKeyScopesAt(
  file: string,
  id: string,
  scopes: unknown,
): Promise<StoredKey | null> {
  const all = await readAll(file);
  const idx = all.findIndex((k) => k.id === id);
  if (idx === -1) return null;
  all[idx] = { ...all[idx], scopes: normalizeScopes(scopes) };
  await writeAll(file, all);
  return all[idx];
}

// ---- Per-key source-IP allowlist ------------------------------------
//
// Enterprise customers routinely require that a long-lived programmatic
// credential only be honored from a fixed egress (a CI runner pool, a
// bastion, a corporate NAT). The allowlist is enforced at the same
// authentication boundary that verifies the key, so a leaked token alone
// is not enough to drive the API from a laptop on a coffee-shop network.

const MAX_ALLOWED_CIDRS = 64;

function parseIPv4(addr: string): number[] | null {
  const parts = addr.split(".");
  if (parts.length !== 4) return null;
  const out: number[] = [];
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p)) return null;
    const n = Number(p);
    if (n < 0 || n > 255) return null;
    out.push(n);
  }
  return out;
}

function parseIPv6(addr: string): number[] | null {
  // Strip optional zone id (e.g. fe80::1%eth0).
  const noZone = addr.split("%")[0];
  // Handle embedded IPv4 in the last 32 bits, e.g. ::ffff:1.2.3.4.
  const v4Match = noZone.match(/(.*:)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$/);
  let normalized = noZone;
  if (v4Match) {
    const v4 = parseIPv4(v4Match[2]);
    if (!v4) return null;
    const hi = ((v4[0] << 8) | v4[1]).toString(16);
    const lo = ((v4[2] << 8) | v4[3]).toString(16);
    normalized = `${v4Match[1]}${hi}:${lo}`;
  }
  const halves = normalized.split("::");
  if (halves.length > 2) return null;
  const left = halves[0] ? halves[0].split(":") : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const explicit = halves.length === 1 ? left : [];
  const groups = halves.length === 1 ? explicit : [...left, ...right];
  for (const g of groups) {
    if (g === "" || g.length > 4 || !/^[0-9a-fA-F]+$/.test(g)) return null;
  }
  if (halves.length === 1 && groups.length !== 8) return null;
  if (halves.length === 2 && left.length + right.length > 8) return null;
  const filler = halves.length === 2 ? 8 - (left.length + right.length) : 0;
  const full: number[] = [];
  for (const g of left) full.push(parseInt(g || "0", 16));
  for (let i = 0; i < filler; i++) full.push(0);
  for (const g of right) full.push(parseInt(g || "0", 16));
  if (full.length !== 8) return null;
  // Return as 16 bytes.
  const bytes: number[] = [];
  for (const g of full) {
    bytes.push((g >> 8) & 0xff, g & 0xff);
  }
  return bytes;
}

function parseAddress(addr: string): { bytes: number[]; bits: number } | null {
  const v4 = parseIPv4(addr);
  if (v4) return { bytes: v4, bits: 32 };
  if (addr.includes(":")) {
    const v6 = parseIPv6(addr);
    if (v6) return { bytes: v6, bits: 128 };
  }
  return null;
}

export function normalizeCidr(entry: string): string | null {
  if (typeof entry !== "string") return null;
  const raw = entry.trim().toLowerCase();
  if (!raw) return null;
  const slash = raw.indexOf("/");
  const addrPart = slash === -1 ? raw : raw.slice(0, slash);
  const suffix = slash === -1 ? null : raw.slice(slash + 1);
  const parsed = parseAddress(addrPart);
  if (!parsed) return null;
  let prefix = parsed.bits;
  if (suffix !== null) {
    if (!/^\d{1,3}$/.test(suffix)) return null;
    prefix = Number(suffix);
    if (prefix < 0 || prefix > parsed.bits) return null;
  }
  // Render canonical form. For IPv4 we use dotted; for IPv6 we use the
  // simple colon-grouped form (not the fully compressed :: form, to keep
  // round-trips stable across edits).
  if (parsed.bits === 32) {
    return `${parsed.bytes.join(".")}/${prefix}`;
  }
  const groups: string[] = [];
  for (let i = 0; i < 16; i += 2) {
    groups.push(((parsed.bytes[i] << 8) | parsed.bytes[i + 1]).toString(16));
  }
  return `${groups.join(":")}/${prefix}`;
}

export function normalizeCidrs(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of input) {
    const norm = normalizeCidr(typeof raw === "string" ? raw : "");
    if (norm === null) {
      throw new Error(
        `Not a valid IP or CIDR: ${String(raw)}. Use forms like 203.0.113.4 or 2001:db8::/32.`,
      );
    }
    if (!seen.has(norm)) {
      seen.add(norm);
      out.push(norm);
    }
  }
  if (out.length > MAX_ALLOWED_CIDRS) {
    throw new Error(`Too many entries (max ${MAX_ALLOWED_CIDRS}).`);
  }
  return out;
}

function matchPrefix(addrBytes: number[], netBytes: number[], prefix: number): boolean {
  if (addrBytes.length !== netBytes.length) return false;
  let remaining = prefix;
  for (let i = 0; i < addrBytes.length && remaining > 0; i++) {
    if (remaining >= 8) {
      if (addrBytes[i] !== netBytes[i]) return false;
      remaining -= 8;
    } else {
      const mask = (0xff << (8 - remaining)) & 0xff;
      if ((addrBytes[i] & mask) !== (netBytes[i] & mask)) return false;
      remaining = 0;
    }
  }
  return true;
}

export function ipAllowed(
  key: { allowed_cidrs?: string[] },
  clientIp: string | null,
): boolean {
  const list = key.allowed_cidrs ?? [];
  if (list.length === 0) return true; // unrestricted (legacy default)
  if (!clientIp) return false;
  const parsed = parseAddress(clientIp.trim());
  if (!parsed) return false;
  for (const entry of list) {
    const slash = entry.indexOf("/");
    const addr = slash === -1 ? entry : entry.slice(0, slash);
    const prefix = slash === -1 ? parsed.bits : Number(entry.slice(slash + 1));
    const net = parseAddress(addr);
    if (!net) continue;
    if (net.bytes.length !== parsed.bytes.length) continue;
    if (matchPrefix(parsed.bytes, net.bytes, prefix)) return true;
  }
  return false;
}

export async function setKeyAllowedCidrsAt(
  file: string,
  id: string,
  cidrs: unknown,
): Promise<StoredKey | null> {
  const normalized = normalizeCidrs(cidrs); // throws on bad input
  const all = await readAll(file);
  const idx = all.findIndex((k) => k.id === id);
  if (idx === -1) return null;
  all[idx] = { ...all[idx], allowed_cidrs: normalized };
  await writeAll(file, all);
  return all[idx];
}
