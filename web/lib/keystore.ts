// Server-only wrapper around `keystore-core` that pins the store location and
// guards against accidental client-side imports. The pure logic lives in
// `keystore-core.ts` so it can be unit-tested without Next.js in the loop.
import "server-only";
import {
  defaultStorePath,
  listKeysAt,
  createKeyAt,
  rotateKeyAt,
  deleteKeyAt,
  verifyAndTouchAt,
  getKeyAt,
  renameKeyAt,
  setKeyScopesAt,
  dailyUsageSeries,
  type StoredKey,
  type CreatedKey,
  type KeyScope,
} from "./keystore-core";

export type { StoredKey, CreatedKey, KeyScope } from "./keystore-core";
export { hasScope, normalizeScopes, ALL_SCOPES, dailyUsageSeries } from "./keystore-core";

const STORE_PATH = defaultStorePath();

export function listKeys(): Promise<StoredKey[]> {
  return listKeysAt(STORE_PATH);
}

export function createKey(name: string, scopes?: unknown): Promise<CreatedKey> {
  return createKeyAt(STORE_PATH, name, scopes);
}

export function rotateKey(id: string): Promise<CreatedKey | null> {
  return rotateKeyAt(STORE_PATH, id);
}

export function deleteKey(id: string): Promise<boolean> {
  return deleteKeyAt(STORE_PATH, id);
}

export function verifyAndTouch(plaintext: string): Promise<StoredKey | null> {
  return verifyAndTouchAt(STORE_PATH, plaintext);
}

export function getKey(id: string): Promise<StoredKey | null> {
  return getKeyAt(STORE_PATH, id);
}

export function renameKey(
  id: string,
  name: string,
): Promise<StoredKey | null> {
  return renameKeyAt(STORE_PATH, id, name);
}

export function setKeyScopes(
  id: string,
  scopes: unknown,
): Promise<StoredKey | null> {
  return setKeyScopesAt(STORE_PATH, id, scopes);
}
