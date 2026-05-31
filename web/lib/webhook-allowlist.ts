// Persisted allowlist of hostnames that are permitted as webhook destinations
// even though they would otherwise be blocked by the SSRF guard (private IP,
// link-local, etc). Cloud-metadata addresses are never overridable.
//
// Stored per workspace under the same store dir as webhooks.json. The legacy
// single-file location (webhook_allowlist.json) is migrated on first read to
// the default workspace so older installs keep their entries.
import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";
import { DEFAULT_WORKSPACE_ID, normalizeWorkspaceId } from "./keystore-core";

const ROOT =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const LEGACY_FILE = path.join(ROOT, "webhook_allowlist.json");

function fileFor(workspaceId: string): string {
  const ws = normalizeWorkspaceId(workspaceId);
  if (ws === DEFAULT_WORKSPACE_ID) return LEGACY_FILE;
  return path.join(ROOT, `webhook_allowlist.${ws}.json`);
}

type Shape = { hostnames: string[] };

function normalize(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of input) {
    if (typeof raw !== "string") continue;
    const v = raw.trim().toLowerCase();
    if (!v) continue;
    if (!/^[a-z0-9.\-:[\]]+$/.test(v)) continue;
    if (v.length > 253) continue;
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

export async function readWebhookAllowlist(
  workspaceId: string = DEFAULT_WORKSPACE_ID,
): Promise<string[]> {
  const file = fileFor(workspaceId);
  try {
    const raw = await fs.readFile(file, "utf8");
    const parsed = JSON.parse(raw) as Shape;
    return normalize(parsed?.hostnames);
  } catch (err: any) {
    if (err?.code === "ENOENT") return [];
    return [];
  }
}

export async function writeWebhookAllowlist(
  input: unknown,
  workspaceId: string = DEFAULT_WORKSPACE_ID,
): Promise<string[]> {
  const file = fileFor(workspaceId);
  const next = normalize(input);
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, JSON.stringify({ hostnames: next }, null, 2), "utf8");
  await fs.rename(tmp, file);
  return next;
}
