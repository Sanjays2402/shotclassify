// Simple file-backed API key store.
// Keys are stored as sha256 hashes; the plaintext token is shown to the user
// exactly once at creation time. The store lives outside the repo and is
// safe to delete (it will be recreated empty on next write).
import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export type StoredKey = {
  id: string;
  name: string;
  prefix: string;        // first 10 chars of the plaintext token, for display
  hash: string;          // sha256(plaintext)
  created_at: string;    // ISO
  last_used_at: string | null;
  usage_count: number;
};

export type CreatedKey = {
  key: StoredKey;
  plaintext: string;     // returned once
};

const STORE_PATH =
  process.env.SHOTCLASSIFY_KEYS_FILE ||
  path.join(process.cwd(), "..", "storage", "api_keys.json");

async function ensureDir() {
  await fs.mkdir(path.dirname(STORE_PATH), { recursive: true });
}

async function readAll(): Promise<StoredKey[]> {
  try {
    const raw = await fs.readFile(STORE_PATH, "utf8");
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as StoredKey[];
  } catch (err: any) {
    if (err?.code === "ENOENT") return [];
    throw err;
  }
}

async function writeAll(keys: StoredKey[]): Promise<void> {
  await ensureDir();
  const tmp = `${STORE_PATH}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(keys, null, 2), "utf8");
  await fs.rename(tmp, STORE_PATH);
}

function sha256(s: string): string {
  return crypto.createHash("sha256").update(s).digest("hex");
}

export async function listKeys(): Promise<StoredKey[]> {
  const all = await readAll();
  // Newest first.
  return all.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export async function createKey(name: string): Promise<CreatedKey> {
  const cleanName = (name || "").trim().slice(0, 80) || "Untitled key";
  // Token format: sk_live_<24 url-safe bytes>
  const raw = crypto.randomBytes(24).toString("base64url");
  const plaintext = `sk_live_${raw}`;
  const key: StoredKey = {
    id: crypto.randomUUID(),
    name: cleanName,
    prefix: plaintext.slice(0, 12),
    hash: sha256(plaintext),
    created_at: new Date().toISOString(),
    last_used_at: null,
    usage_count: 0,
  };
  const all = await readAll();
  all.push(key);
  await writeAll(all);
  return { key, plaintext };
}

export async function deleteKey(id: string): Promise<boolean> {
  const all = await readAll();
  const next = all.filter((k) => k.id !== id);
  if (next.length === all.length) return false;
  await writeAll(next);
  return true;
}

export async function verifyAndTouch(
  plaintext: string,
): Promise<StoredKey | null> {
  if (!plaintext || !plaintext.startsWith("sk_live_")) return null;
  const hash = sha256(plaintext);
  const all = await readAll();
  const match = all.find((k) => k.hash === hash);
  if (!match) return null;
  match.last_used_at = new Date().toISOString();
  match.usage_count += 1;
  await writeAll(all);
  return match;
}
