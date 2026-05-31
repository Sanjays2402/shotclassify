// Proxy for FastAPI /v1/audit (admin-only audit log read API).
// The browser session cookie or workspace API key is forwarded to FastAPI,
// which enforces RBAC (admin role) and tenant scoping. This route adds no
// auth of its own; FastAPI is authoritative.
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest): HeadersInit {
  const h: Record<string, string> = {};
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) {
    h["cookie"] = cookie;
  } else if (KEY) {
    h["x-api-key"] = KEY;
  }
  const tenant = req.headers.get("x-tenant");
  if (tenant) h["x-tenant"] = tenant;
  return h;
}

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const qs = new URLSearchParams();
  const limit = url.searchParams.get("limit");
  const principal = url.searchParams.get("principal");
  const pathPrefix = url.searchParams.get("path_prefix");
  if (limit) qs.set("limit", limit);
  if (principal) qs.set("principal", principal);
  if (pathPrefix) qs.set("path_prefix", pathPrefix);
  const wantExport = url.searchParams.get("format") === "csv";

  const r = await fetch(`${API}/v1/audit?${qs.toString()}`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  const text = await r.text();
  if (!r.ok) {
    return new NextResponse(text, {
      status: r.status,
      headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
    });
  }
  if (!wantExport) {
    return new NextResponse(text, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }
  // CSV export: flatten the events array into a downloadable file.
  let payload: any;
  try {
    payload = JSON.parse(text);
  } catch {
    return new NextResponse("invalid upstream payload", { status: 502 });
  }
  const events: any[] = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.events)
      ? payload.events
      : [];
  const cols = [
    "created_at",
    "principal",
    "method",
    "path",
    "status_code",
    "client_ip",
    "tenant_id",
    "request_id",
    "elapsed_ms",
  ];
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [cols.join(",")];
  for (const e of events) lines.push(cols.map((c) => esc(e?.[c])).join(","));
  return new NextResponse(lines.join("\n"), {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="audit-log-${new Date()
        .toISOString()
        .slice(0, 10)}.csv"`,
    },
  });
}
