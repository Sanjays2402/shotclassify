import { promises as fs } from "node:fs";
import path from "node:path";

import { NextRequest, NextResponse } from "next/server";

import {
  makePeriod,
  renderDigestHTML,
  renderDigestText,
  renderEml,
  summarize,
  type DigestRow,
} from "@/lib/digest";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";
const STORE_DIR =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const OUTBOX = path.join(STORE_DIR, "digest_outbox");

function authHeaders(req: NextRequest): HeadersInit {
  const h: Record<string, string> = {};
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) {
    h["cookie"] = cookie;
  } else if (KEY) {
    h["x-api-key"] = KEY;
  }
  return h;
}

function appUrl(req: NextRequest): string {
  const fwdHost = req.headers.get("x-forwarded-host");
  const host = fwdHost || req.headers.get("host") || "localhost:3000";
  const proto = req.headers.get("x-forwarded-proto") || "http";
  return `${proto}://${host}`;
}

async function fetchRows(req: NextRequest, since: string): Promise<DigestRow[]> {
  // Pull at most 500 rows since `since`; enough for a digest window.
  const qs = new URLSearchParams({
    since,
    limit: "500",
    offset: "0",
    sort: "new",
  });
  const url = `${API}/v1/history?${qs.toString()}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: authHeaders(req), cache: "no-store" });
  } catch {
    return [];
  }
  if (!res.ok) return [];
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    return [];
  }
  const items = (body as { items?: unknown[]; data?: unknown[] }).items
    ?? (body as { data?: unknown[] }).data
    ?? (Array.isArray(body) ? (body as unknown[]) : []);
  const out: DigestRow[] = [];
  for (const raw of items) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    const id = String(r.id ?? "");
    const cat = String(r.primary_category ?? r.category ?? "");
    const created = String(r.created_at ?? r.createdAt ?? "");
    if (!id || !cat || !created) continue;
    out.push({
      id,
      filename: typeof r.filename === "string" ? r.filename : null,
      primary_category: cat,
      confidence: typeof r.confidence === "number" ? r.confidence : 0,
      created_at: created,
      source: typeof r.source === "string" ? r.source : null,
    });
  }
  return out;
}

function parseDays(raw: string | null): number {
  const n = Number(raw ?? "7");
  if (!Number.isFinite(n)) return 7;
  return Math.max(1, Math.min(90, Math.floor(n)));
}

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const days = parseDays(url.searchParams.get("days"));
  const format = (url.searchParams.get("format") || "json").toLowerCase();
  const now = new Date();
  const period = makePeriod(days, now);
  const rows = await fetchRows(req, period.since);
  const summary = summarize(rows, period, now);
  const base = appUrl(req);

  if (format === "text" || format === "txt") {
    return new NextResponse(renderDigestText(summary, base), {
      status: 200,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
  if (format === "html") {
    return new NextResponse(renderDigestHTML(summary, base), {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }
  return NextResponse.json({
    summary,
    text: renderDigestText(summary, base),
    html: renderDigestHTML(summary, base),
  });
}

function sanitizeEmail(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const v = raw.trim().toLowerCase();
  if (!v) return null;
  if (v.length > 254) return null;
  // minimal email shape check
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return null;
  return v;
}

export async function POST(req: NextRequest) {
  let body: unknown = null;
  try {
    body = await req.json();
  } catch {
    /* allow empty body */
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const days = parseDays(typeof obj.days === "number" ? String(obj.days) : (obj.days as string | null) ?? null);
  const to = sanitizeEmail(obj.to) ?? process.env.DIGEST_TO ?? "owner@shotclassify.local";
  const from = process.env.DIGEST_FROM ?? "noreply@shotclassify.local";

  const now = new Date();
  const period = makePeriod(days, now);
  const rows = await fetchRows(req, period.since);
  const summary = summarize(rows, period, now);
  const base = appUrl(req);
  const text = renderDigestText(summary, base);
  const html = renderDigestHTML(summary, base);
  const subject = summary.empty
    ? `ShotClassify digest (no activity, last ${period.days}d)`
    : `ShotClassify digest: ${summary.total_shots} shots, last ${period.days}d`;
  const eml = renderEml({ to, from, subject, text, html });

  await fs.mkdir(OUTBOX, { recursive: true });
  const stamp = now.toISOString().replace(/[:.]/g, "-");
  const safeTo = to.replace(/[^a-z0-9@._-]/g, "_");
  const filename = `${stamp}__${safeTo}.eml`;
  const full = path.join(OUTBOX, filename);
  await fs.writeFile(full, eml, "utf8");

  return NextResponse.json({
    ok: true,
    delivered: false, // SMTP not configured in this deploy
    transport: "outbox",
    path: full,
    subject,
    to,
    from,
    bytes: Buffer.byteLength(eml, "utf8"),
    summary: {
      total_shots: summary.total_shots,
      days: summary.period.days,
      avg_confidence: summary.avg_confidence,
    },
  });
}
