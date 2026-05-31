// Readiness probe. Distinct from /healthz: returns 503 when a dependency the
// process needs to serve requests is unavailable, so a load balancer pulls the
// pod out of rotation without killing it. Checks today:
//   1. Upstream FastAPI /healthz (the actual classifier) reachable.
//   2. Keystore directory writable (auth depends on it).
import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import { resolveRequestId } from "@/lib/metrics";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const READY_TIMEOUT_MS = Number(process.env.SHOTCLASSIFY_READY_TIMEOUT_MS || 1500);

type CheckResult = { name: string; ok: boolean; detail?: string };

async function checkUpstream(): Promise<CheckResult> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), READY_TIMEOUT_MS);
  try {
    const r = await fetch(`${API}/healthz`, { signal: ctl.signal });
    if (!r.ok) return { name: "upstream_api", ok: false, detail: `status ${r.status}` };
    return { name: "upstream_api", ok: true };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { name: "upstream_api", ok: false, detail: msg };
  } finally {
    clearTimeout(t);
  }
}

async function checkKeystore(): Promise<CheckResult> {
  // Match the resolution rule in keystore-core's defaultStorePath: prefer the
  // explicit env var, otherwise the repo-local storage directory.
  const dir =
    process.env.SHOTCLASSIFY_KEYSTORE_DIR ||
    path.resolve(process.cwd(), "..", "storage");
  try {
    await fs.mkdir(dir, { recursive: true });
    await fs.access(dir, fs.constants.W_OK);
    return { name: "keystore", ok: true };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { name: "keystore", ok: false, detail: msg };
  }
}

export async function GET(req: Request): Promise<Response> {
  const rid = resolveRequestId(req.headers);
  const checks = await Promise.all([checkUpstream(), checkKeystore()]);
  const ok = checks.every((c) => c.ok);
  return NextResponse.json(
    { status: ok ? "ready" : "not_ready", checks },
    {
      status: ok ? 200 : 503,
      headers: { "cache-control": "no-store", "x-request-id": rid },
    },
  );
}
