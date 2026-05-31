// Pure, no `server-only`, no Next deps. Used by `keystore.ts` AND by tests.
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export type StoredKey = {
  id: string;
  name: string;
  prefix: string;
  hash: string;
  created_at: string;
  last_used_at: string | null;
  usage_count: number;
  rotated_at?: string | null;
};

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
  match.last_used_at = new Date().toISOString();
  match.usage_count += 1;
  await writeAll(file, all);
  return match;
}
