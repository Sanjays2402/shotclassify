// Shared helpers for /v1/* programmatic endpoints.
// Centralizes API-key extraction, validation, and structured error envelopes.
import "server-only";
import { NextRequest, NextResponse } from "next/server";
import { verifyAndTouch, hasScope, workspaceOf, ipAllowed, type StoredKey, type KeyScope } from "@/lib/keystore";
import { enforce, snapshotFor } from "@/lib/ratelimit";

export const UPSTREAM_API =
  process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
export const UPSTREAM_KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export function extractToken(req: NextRequest): string | null {
  const auth = req.headers.get("authorization") || "";
  const m = auth.match(/^Bearer\s+(\S+)$/i);
  if (m) return m[1];
  const xk = req.headers.get("x-api-key");
  if (xk) return xk;
  return null;
}

/**
 * Best-effort source IP for an inbound request. Honours the first entry of
 * X-Forwarded-For when present (per RFC 7239 conventions) and falls back to
 * the connection-level address Next.js exposes. Returns null when no IP can
 * be determined, in which case an allowlist-protected key denies access.
 */
export function clientIp(req: NextRequest): string | null {
  const xff = req.headers.get("x-forwarded-for");
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) return first;
  }
  const real = req.headers.get("x-real-ip");
  if (real) return real.trim();
  // NextRequest exposes `.ip` on some runtimes; tolerate its absence.
  const maybe = (req as unknown as { ip?: string | null }).ip;
  return maybe ?? null;
}

export function v1Error(
  status: number,
  code: string,
  message: string,
): NextResponse {
  return NextResponse.json(
    { error: { code, message } },
    { status, headers: { "content-type": "application/json" } },
  );
}

export type AuthOk = { key: StoredKey; rateHeaders: Record<string, string> };

export async function authenticate(
  req: NextRequest,
  requiredScope: KeyScope = "read",
): Promise<AuthOk | NextResponse> {
  const token = extractToken(req);
  if (!token) {
    return v1Error(
      401,
      "missing_credentials",
      "Provide an API key via 'Authorization: Bearer sk_live_...'",
    );
  }
  const key = await verifyAndTouch(token);
  if (!key) {
    return v1Error(401, "invalid_key", "API key is invalid or revoked.");
  }
  if (!hasScope(key, requiredScope)) {
    return v1Error(
      403,
      "insufficient_scope",
      `This API key is missing the '${requiredScope}' scope.`,
    );
  }
  const ip = clientIp(req);
  if (!ipAllowed(key, ip)) {
    return v1Error(
      403,
      "ip_not_allowed",
      `This API key is restricted to a fixed source-IP allowlist and the calling address${ip ? ` (${ip})` : ""} is not in it.`,
    );
  }
  const decision = await enforce(workspaceOf(key), key.id);
  if (!decision.allowed) {
    const res = NextResponse.json(
      {
        error: {
          code: "rate_limited",
          message: `Rate limit exceeded (${decision.bounded_by}). Retry in ${decision.retry_after_seconds}s.`,
          bounded_by: decision.bounded_by,
          retry_after_seconds: decision.retry_after_seconds,
        },
      },
      { status: 429 },
    );
    for (const [k, v] of Object.entries(decision.headers)) res.headers.set(k, v);
    return res;
  }
  return { key, rateHeaders: decision.headers };
}

export function keyHeaders(
  key: StoredKey,
  rateHeaders?: Record<string, string>,
): Record<string, string> {
  return {
    "x-api-key-id": key.id,
    "x-api-key-usage": String(key.usage_count),
    "x-api-key-scopes": (key.scopes ?? ["read", "write"]).join(","),
    "x-workspace-id": workspaceOf(key),
    ...(rateHeaders ?? {}),
  };
}

export function rateSnapshot(key: StoredKey) {
  return snapshotFor(workspaceOf(key), key.id);
}

export async function proxyUpstream(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (UPSTREAM_KEY && !headers.has("x-api-key")) {
    headers.set("x-api-key", UPSTREAM_KEY);
  }
  return fetch(`${UPSTREAM_API}${path}`, { ...init, headers });
}
