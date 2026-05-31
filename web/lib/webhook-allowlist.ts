// Persisted allowlist of hostnames that are permitted as webhook destinations
// even though they would otherwise be blocked by the SSRF guard (private IP,
// link-local, etc). Cloud-metadata addresses are never overridable.
//
// Stored as a small JSON file under the same store dir as webhooks.json.
// Admin-only via the /api/settings/security/webhook-allowlist route.
import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";

const ROOT =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const FILE = path.join(ROOT, "webhook_allowlist.json");

type Shape = { hostnames: string[] };

function normalize(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of input) {
    if (typeof raw !== "string") continue;
    const v = raw.trim().toLowerCase();
    if (!v) continue;
    // Reject obvious junk so a typo in the admin UI cannot poison the file.
    if (!/^[a-z0-9.\-:[\]]+$/.test(v)) continue;
    if (v.length > 253) continue;
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

export async function readWebhookAllowlist(): Promise<string[]> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    const parsed = JSON.parse(raw) as Shape;
    return normalize(parsed?.hostnames);
  } catch (err: any) {
    if (err?.code === "ENOENT") return [];
    return [];
  }
}

export async function writeWebhookAllowlist(input: unknown): Promise<string[]> {
  const next = normalize(input);
  await fs.mkdir(path.dirname(FILE), { recursive: true });
  const tmp = `${FILE}.tmp`;
  await fs.writeFile(tmp, JSON.stringify({ hostnames: next }, null, 2), "utf8");
  await fs.rename(tmp, FILE);
  return next;
}
